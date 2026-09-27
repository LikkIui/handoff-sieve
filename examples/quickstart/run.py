"""Offline RelayGuard quickstart."""

from pathlib import Path

from relayguard import HandoffPipeline, Message

HERE = Path(__file__).resolve().parent


def main() -> None:
    pipeline = HandoffPipeline.from_yaml(HERE / "handoffs.yaml")
    repeated_note = "Search result: repeated background information. " * 8
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=[
            repeated_note,
            repeated_note,
            "Additional low-priority context. " * 20,
            Message(
                kind="structured",
                tags={"conclusion", "constraint"},
                content={
                    "conclusions": ["The project is feasible."],
                    "constraints": ["The final answer must cite its sources."],
                    "contact": "alice@example.com",
                    "test_key": "sk-example123456",
                },
            ),
        ],
    )

    print(result.report.to_text())
    print("\nTransmitted messages:")
    for message in result.messages:
        print(f"- {message.content}")


if __name__ == "__main__":
    main()
