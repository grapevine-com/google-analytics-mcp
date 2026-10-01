# Copyright 2026 Grapevine
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Google credentials for running the server inside AWS.

Upstream resolves credentials with Application Default Credentials (ADC). On
AgentCore Runtime there is no gcloud login, so this module builds credentials
from the runtime's AWS identity instead, choosing a mode from the environment:

- Workload Identity Federation (keyless, preferred): set
  ``GOOGLE_WIF_AUDIENCE`` and ``GOOGLE_SERVICE_ACCOUNT_EMAIL``. The runtime's
  AWS credentials (from boto3, so they refresh) are exchanged for a short-lived
  Google token that impersonates the service account.
- Service account key in Secrets Manager (fallback): set
  ``GOOGLE_CREDENTIALS_SECRET_ARN``.
- Neither: fall back to upstream's ADC, for local development.
"""

import json
import os

import boto3
import google.auth.aws
from google.oauth2 import service_account

from analytics_mcp.tools import client

_AWS_SUBJECT_TOKEN_TYPE = "urn:ietf:params:aws:token-type:aws4_request"
_IMPERSONATION_URL = (
    "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
    "{email}:generateAccessToken"
)


class Boto3AwsCredentialsSupplier(
    google.auth.aws.AwsSecurityCredentialsSupplier
):
    """Supplies the runtime's AWS credentials, refreshed by boto3."""

    def __init__(self, session=None):
        self._session = session or boto3.Session()

    def get_aws_security_credentials(self, context, request):
        credentials = self._session.get_credentials()
        if credentials is None:
            raise RuntimeError("no AWS credentials available for WIF")
        frozen = credentials.get_frozen_credentials()
        return google.auth.aws.AwsSecurityCredentials(
            frozen.access_key, frozen.secret_key, frozen.token
        )

    def get_aws_region(self, context, request):
        region = self._session.region_name or os.environ.get("AWS_REGION")
        if not region:
            raise RuntimeError("no AWS region available for WIF")
        return region


def workload_identity_credentials(
    audience, service_account_email, session=None
):
    """Returns Google credentials federated from the AWS identity."""
    return google.auth.aws.Credentials(
        audience=audience,
        subject_token_type=_AWS_SUBJECT_TOKEN_TYPE,
        aws_security_credentials_supplier=Boto3AwsCredentialsSupplier(session),
        service_account_impersonation_url=_IMPERSONATION_URL.format(
            email=service_account_email
        ),
        scopes=[client._READ_ONLY_ANALYTICS_SCOPE],
    )


def secret_key_credentials(secret_arn, session=None):
    """Returns Google credentials from a service account key secret."""
    secrets = (session or boto3.Session()).client("secretsmanager")
    secret = secrets.get_secret_value(SecretId=secret_arn)
    return service_account.Credentials.from_service_account_info(
        json.loads(secret["SecretString"]),
        scopes=[client._READ_ONLY_ANALYTICS_SCOPE],
    )


def credentials_from_env(environ=None, session=None):
    """Returns credentials for the configured mode, or None for ADC."""
    environ = os.environ if environ is None else environ
    audience = environ.get("GOOGLE_WIF_AUDIENCE")
    email = environ.get("GOOGLE_SERVICE_ACCOUNT_EMAIL")
    secret_arn = environ.get("GOOGLE_CREDENTIALS_SECRET_ARN")
    if audience or email:
        if not (audience and email):
            raise RuntimeError(
                "GOOGLE_WIF_AUDIENCE and GOOGLE_SERVICE_ACCOUNT_EMAIL must be"
                " set together"
            )
        return workload_identity_credentials(audience, email, session)
    if secret_arn:
        return secret_key_credentials(secret_arn, session)
    return None


def install_credentials(environ=None, session=None):
    """Points upstream's API clients at the configured credentials.

    Returns the mode name, for logging. Upstream caches credentials in
    ``client._CREDENTIALS`` and only calls ADC when it is unset, so setting it
    here is enough; no upstream file changes.
    """
    credentials = credentials_from_env(environ, session)
    if credentials is None:
        return "adc"
    with client._client_lock:
        client._CREDENTIALS = credentials
    if isinstance(credentials, google.auth.aws.Credentials):
        return "workload-identity"
    return "secret-key"
