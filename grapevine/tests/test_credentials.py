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

"""Tests for building Google credentials from the AWS runtime identity."""

import json
import unittest
from unittest import mock

import google.auth.aws
from botocore.credentials import Credentials as BotoCredentials
from google.oauth2 import service_account

from analytics_mcp.tools import client
from grapevine import credentials

AUDIENCE = (
    "//iam.googleapis.com/projects/123/locations/global/"
    "workloadIdentityPools/aws/providers/grapevine"
)
EMAIL = "ga-mcp@grapevine-ga.iam.gserviceaccount.com"


def fake_session(region="us-east-1", boto_credentials=None):
    session = mock.Mock()
    session.region_name = region
    session.get_credentials.return_value = boto_credentials
    return session


class CredentialsFromEnvTest(unittest.TestCase):

    def test_no_configuration_means_adc(self):
        self.assertIsNone(credentials.credentials_from_env({}))

    def test_workload_identity(self):
        result = credentials.credentials_from_env(
            {
                "GOOGLE_WIF_AUDIENCE": AUDIENCE,
                "GOOGLE_SERVICE_ACCOUNT_EMAIL": EMAIL,
            },
            session=fake_session(),
        )

        self.assertIsInstance(result, google.auth.aws.Credentials)
        self.assertEqual(result.info["audience"], AUDIENCE)
        self.assertEqual(result.service_account_email, EMAIL)
        self.assertEqual(result.scopes, [client._READ_ONLY_ANALYTICS_SCOPE])

    def test_partial_workload_identity_config_fails_loudly(self):
        with self.assertRaisesRegex(RuntimeError, "set together"):
            credentials.credentials_from_env({"GOOGLE_WIF_AUDIENCE": AUDIENCE})

    def test_secret_key(self):
        key_info = {"type": "service_account", "client_email": EMAIL}
        session = fake_session()
        session.client.return_value.get_secret_value.return_value = {
            "SecretString": json.dumps(key_info)
        }
        with mock.patch.object(
            service_account.Credentials, "from_service_account_info"
        ) as from_info:
            result = credentials.credentials_from_env(
                {"GOOGLE_CREDENTIALS_SECRET_ARN": "arn:secret"},
                session=session,
            )

        session.client.assert_called_once_with("secretsmanager")
        session.client.return_value.get_secret_value.assert_called_once_with(
            SecretId="arn:secret"
        )
        from_info.assert_called_once_with(
            key_info, scopes=[client._READ_ONLY_ANALYTICS_SCOPE]
        )
        self.assertIs(result, from_info.return_value)


class Boto3SupplierTest(unittest.TestCase):

    def test_returns_current_boto3_credentials(self):
        supplier = credentials.Boto3AwsCredentialsSupplier(
            fake_session(boto_credentials=BotoCredentials("AK", "SK", "TOK"))
        )

        result = supplier.get_aws_security_credentials(None, None)

        self.assertEqual(
            (result.access_key_id, result.secret_access_key),
            ("AK", "SK"),
        )
        self.assertEqual(result.session_token, "TOK")
        self.assertEqual(supplier.get_aws_region(None, None), "us-east-1")

    def test_missing_aws_credentials(self):
        supplier = credentials.Boto3AwsCredentialsSupplier(fake_session())

        with self.assertRaisesRegex(RuntimeError, "no AWS credentials"):
            supplier.get_aws_security_credentials(None, None)

    def test_region_falls_back_to_env(self):
        supplier = credentials.Boto3AwsCredentialsSupplier(
            fake_session(region=None)
        )

        with mock.patch.dict("os.environ", {"AWS_REGION": "us-west-2"}):
            self.assertEqual(supplier.get_aws_region(None, None), "us-west-2")


class InstallCredentialsTest(unittest.TestCase):

    def setUp(self):
        original = client._CREDENTIALS
        self.addCleanup(setattr, client, "_CREDENTIALS", original)
        client._CREDENTIALS = None

    def test_adc_leaves_upstream_alone(self):
        self.assertEqual(credentials.install_credentials({}), "adc")
        self.assertIsNone(client._CREDENTIALS)

    def test_workload_identity_is_used_by_upstream_clients(self):
        mode = credentials.install_credentials(
            {
                "GOOGLE_WIF_AUDIENCE": AUDIENCE,
                "GOOGLE_SERVICE_ACCOUNT_EMAIL": EMAIL,
            },
            session=fake_session(),
        )

        self.assertEqual(mode, "workload-identity")
        with mock.patch("google.auth.default") as adc:
            self.assertIs(client._get_credentials(), client._CREDENTIALS)
        adc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
