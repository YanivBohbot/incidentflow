import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_cloudwatch_demo.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_cloudwatch_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_role_policy_matches_cloud_permissions() -> None:
    policy = _load_script().demo_role_policy("123456789012", "eu-west-1")

    group = "arn:aws:logs:eu-west-1:123456789012:log-group:/incidentflow/demo/*"
    alarms = "arn:aws:cloudwatch:eu-west-1:123456789012:alarm:if-*"
    assert policy["Version"] == "2012-10-17"
    assert policy["Statement"] == [
        {
            "Effect": "Allow",
            "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:TagResource"],
            "Resource": [group],
        },
        {
            "Effect": "Allow",
            "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
            "Resource": [group, f"{group}:*"],
        },
        {
            "Effect": "Allow",
            "Action": ["cloudwatch:PutMetricData"],
            "Resource": "*",
            "Condition": {"StringEquals": {"cloudwatch:namespace": "IncidentFlow/Demo"}},
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:SetAlarmState",
                "cloudwatch:TagResource",
                "cloudwatch:DescribeAlarms",
            ],
            "Resource": [alarms],
        },
    ]
