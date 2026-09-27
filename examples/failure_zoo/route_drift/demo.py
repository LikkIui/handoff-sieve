"""Failure: a renamed receiver bypasses the intended policy route."""

from relayguard import HandoffPipeline, UnmatchedRouteError
from relayguard.pipeline import PolicyRule
from relayguard.policies import RedactPolicy


def main() -> None:
    pipeline = HandoffPipeline(
        rules=[
            PolicyRule(
                sender="researcher",
                receiver="writer",
                policies=(RedactPolicy(),),
                rule_id="researcher-to-writer",
            )
        ]
    )

    try:
        pipeline.process(
            sender="researcher",
            receiver="typo-writer",
            messages=["route-canary-value"],
        )
    except UnmatchedRouteError as error:
        report = error.report
        assert report is not None
        assert report.status == "denied"
        assert report.failure_code == "unmatched_route"
        assert report.failed_policy == "config"
        assert report.transmitted_tokens == 0
        assert report.completed_at is not None
        assert "route-canary-value" not in report.model_dump_json()
    else:
        raise AssertionError("route drift must fail closed")

    print("Result: unmatched receiver route was denied and audited")


if __name__ == "__main__":
    main()
