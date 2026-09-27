"""Failure: irrelevant context hides the one constraint the receiver needs."""

from relayguard import HandoffPipeline, Message
from relayguard.policies import BudgetPolicy, PreservePolicy


def main() -> None:
    messages = [
        f"Verbose research note {index}: " + "background " * 30 for index in range(20)
    ]
    messages.append(
        Message(
            content="The final answer must include citations.",
            tags={"constraint"},
        )
    )
    pipeline = HandoffPipeline(
        [PreservePolicy(), BudgetPolicy(80, strategy="drop_oldest")]
    )
    result = pipeline.process(
        sender="researcher",
        receiver="writer",
        messages=messages,
    )

    assert result.report.transmitted_tokens <= 80
    assert any(message.protected for message in result.messages)
    assert any("citations" in str(message.content) for message in result.messages)

    print(result.report.to_text())
    print("Result: the critical constraint survived the hard budget")


if __name__ == "__main__":
    main()
