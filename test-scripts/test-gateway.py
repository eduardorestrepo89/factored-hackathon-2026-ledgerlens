#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Test AgentCore Gateway directly, without the agent or the frontend.

Acts as a Cognito user: the machine token carries that user's sub in
aws_client_metadata, as the agent's does, so the pre-token Lambda adds the
user's customer_id claim and Cedar applies the per-customer rules.

Usage:
    python test-scripts/test-gateway.py --user-sub <unmapped>  # unlinked login
    python test-scripts/test-gateway.py                        # no user claims
    python test-scripts/test-gateway.py --user-sub <sub>       # list the tools
    python test-scripts/test-gateway.py --user-sub <sub> --customer-id <id>
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
import requests

# Add scripts directory to path for reliable imports
scripts_dir = Path(__file__).parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from utils import get_ssm_params, get_stack_config, print_msg, print_section


def get_secret(secret_name: str) -> str:
    """
    Fetch secret from AWS Secrets Manager.

    Secrets Manager is designed for storing sensitive information like passwords,
    API keys, and other secrets with automatic rotation capabilities.

    Args:
        secret_name: The name or ARN of the secret to retrieve

    Returns:
        The secret value as a string

    Raises:
        ValueError: If the secret is not found or cannot be accessed
        RuntimeError: If there's an AWS service error
    """
    region = os.environ.get(
        "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    secrets_client = boto3.client("secretsmanager", region_name=region)

    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]
    except secrets_client.exceptions.ResourceNotFoundException:
        raise ValueError(f"Secret not found: {secret_name}")
    except secrets_client.exceptions.InvalidParameterException:
        raise ValueError(f"Invalid secret parameter: {secret_name}")
    except secrets_client.exceptions.InvalidRequestException:
        raise ValueError(f"Invalid request for secret: {secret_name}")
    except secrets_client.exceptions.DecryptionFailureException:
        raise RuntimeError(f"Failed to decrypt secret: {secret_name}")
    except secrets_client.exceptions.InternalServiceErrorException:
        raise RuntimeError(
            f"AWS Secrets Manager service error for secret: {secret_name}"
        )
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error retrieving secret {secret_name}: {str(e)}"
        )


def fetch_access_token(
    client_id: str, client_secret: str, token_url: str, user_sub: str | None
) -> str:
    """Fetch a machine token with the client credentials flow.

    With user_sub, the request carries aws_client_metadata the way the agent sends
    it (agent/utils/auth.py), so the pre-token Lambda adds that user's
    customer_id claim. Without it, the claim is blank and Cedar allows no
    LedgerLens tool.
    """
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if user_sub:
        data["aws_client_metadata"] = json.dumps({"verified_user_id": user_sub})

    response = requests.post(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    if response.status_code != 200:
        print_msg(
            f"Token request failed: {response.status_code} - {response.text}", "error"
        )
        sys.exit(1)

    return response.json()["access_token"]


def list_tools(gateway_url: str, access_token: str) -> dict:
    """List available tools via gateway."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    payload = {"jsonrpc": "2.0", "id": "list-tools-request", "method": "tools/list"}

    response = requests.post(gateway_url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print_msg(
            f"Gateway request failed: {response.status_code} - {response.text}", "error"
        )
        sys.exit(1)

    return response.json()


def call_tool(
    gateway_url: str, access_token: str, tool_name: str, arguments: dict
) -> dict:
    """Call a specific tool via gateway."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    payload = {
        "jsonrpc": "2.0",
        "id": "call-tool-request",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    response = requests.post(gateway_url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print_msg(
            f"Gateway request failed: {response.status_code} - {response.text}", "error"
        )
        sys.exit(1)

    return response.json()


def parse_args() -> argparse.Namespace:
    """Read --user-sub and --customer-id."""
    parser = argparse.ArgumentParser(
        description="Call the AgentCore Gateway as a Cognito user, without the agent."
    )
    parser.add_argument(
        "--user-sub",
        help="Cognito sub to act as; its customer_id comes from the pre-token "
        "Lambda's USER_CUSTOMER_IDS_MAP. A sub that isn't in the map tests an "
        "unlinked login (blank customer_id); omitting it gives a token with no "
        "user claims at all.",
    )
    parser.add_argument(
        "--customer-id",
        help="customer_id to pass to list_credit_cards. Omit it to only list the tools.",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    print_section("AgentCore Gateway Direct Test")

    stack_cfg = get_stack_config()
    print(f"Stack: {stack_cfg['stack_name']}\n")

    print("Fetching configuration...")
    gateway_params = get_ssm_params(
        stack_cfg["stack_name"], "gateway_url", "machine_client_id", "cognito_provider"
    )
    client_secret = get_secret(f"/{stack_cfg['stack_name']}/machine_client_secret")
    print_msg("Configuration fetched")

    gateway_url = gateway_params["gateway_url"]
    token_url = f"https://{gateway_params['cognito_provider']}/oauth2/token"
    print(f"Gateway URL: {gateway_url}")

    print_section("Authentication")
    who = f"user {args.user_sub}" if args.user_sub else "no user (no user claims)"
    print(f"Fetching a machine token for {who}...")
    access_token = fetch_access_token(
        gateway_params["machine_client_id"], client_secret, token_url, args.user_sub
    )
    print_msg("Access token obtained", "success")

    print_section("tools/list")
    tools = list_tools(gateway_url, access_token)
    names = [t["name"] for t in tools.get("result", {}).get("tools", [])]
    print_msg(f"{len(names)} tools listed", "success")
    for name in names:
        print(f"  {name}")

    if not args.customer_id:
        return

    print_section("tools/call list_credit_cards")
    tool_name = next((n for n in names if n.endswith("___list_credit_cards")), None)
    if tool_name is None:
        print_msg("list_credit_cards isn't listed for this token", "error")
        sys.exit(1)

    print(f"Calling {tool_name} with customer_id={args.customer_id}...")
    result = call_tool(
        gateway_url, access_token, tool_name, {"customer_id": args.customer_id}
    )
    print(json.dumps(result, indent=2))
    if "error" in result or result.get("result", {}).get("isError"):
        print_msg("The call was refused or failed", "error")
        sys.exit(1)
    print_msg("Tool call successful", "success")


if __name__ == "__main__":
    main()
