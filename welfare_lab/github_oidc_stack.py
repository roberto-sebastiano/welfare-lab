from aws_cdk import Stack, CfnOutput, Duration, aws_iam as iam
from constructs import Construct


class GithubOidcStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, sub_prefix: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Registra GitHub come identity provider nell'account (uno per account)
        provider = iam.OpenIdConnectProvider(self, "GithubProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        # Ruolo assumibile SOLO da questo repo, e solo in due casi:
        # job lanciati da una pull request, oppure job nell'environment "prod"
        role = iam.Role(self, "DeployRole",
            role_name="welfare-lab-github-deploy",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": [
                            f"{sub_prefix}:pull_request",
                            f"{sub_prefix}:environment:prod",
                        ],
                    },
                },
            ),
        )

        # Unico permesso: assumere i ruoli creati da cdk bootstrap
        role.add_to_policy(iam.PolicyStatement(
            actions=["sts:AssumeRole"],
            resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*"],
        ))

        CfnOutput(self, "DeployRoleArn", value=role.role_arn)