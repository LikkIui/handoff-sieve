"""Failure: a naive summary replaces a critical instruction."""

from relayguard import HandoffPipeline, Message
from relayguard.policies import MockSummarizer, PreservePolicy, SummarizePolicy


def main() -> None:
    constraint = Message(
        content="Never publish the draft without human approval.",
        tags={"constraint"},
    )
    discussion = [
        constraint,
        "Several long brainstorming notes about tone and structure.",
        "More low-priority discussion and repeated alternatives.",
    ]

    naive_summary = "The team discussed tone and structure."
    assert "human approval" not in naive_summary

    pipeline = HandoffPipeline(
        [
            PreservePolicy(),
            SummarizePolicy(
                MockSummarizer("The team discussed tone and structure."),
                max_tokens=30,
            ),
        ]
    )
    result = pipeline.process(
        sender="planner",
        receiver="publisher",
        messages=discussion,
    )
    transmitted = "\n".join(str(message.content) for message in result.messages)

    assert "human approval" in transmitted
    assert result.report.protected_messages == 1

    print("Naive summary:", naive_summary)
    print("RelayGuard handoff:", transmitted)
    print("Result: the protected constraint survived summarization")


if __name__ == "__main__":
    main()
