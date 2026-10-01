import textwrap

import pytest

pytest.importorskip("tree_sitter_go")

from jevvify.languages import adapter_named  # noqa: E402

GO = adapter_named("go")

SRC = textwrap.dedent('''
    package support

    import (
        "context"
        "fmt"

        "github.com/openai/openai-go"
    )

    func Route(ctx context.Context, client openai.Client, ticket string) (string, error) {
        prompt := fmt.Sprintf("Route to billing or support. Reply with one word.\\nTicket: %s", ticket)
        resp, err := client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
            Model:    openai.ChatModelGPT4o,
            Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage(prompt)},
        })
        if err != nil {
            return "", err
        }
        return resp.Choices[0].Message.Content, nil
    }

    func Reply(ctx context.Context, client openai.Client, ticket string) {
        client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
            Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage("Write a friendly reply to: " + ticket)},
        })
    }

    func Stream(ctx context.Context, client openai.Client, t string) {
        client.Chat.Completions.NewStreaming(ctx, openai.ChatCompletionNewParams{})
    }
''')


def test_go_detection_is_manual_only():
    route, reply, stream = GO.analyze(SRC, "support/route.go")
    assert (route.status, route.kind, route.options, route.rewritable) == ("candidate", "choice",
                                                                           ["billing", "support"], False)
    assert route.variables == {"ticket": "ticket"} and route.language == "go"
    assert "manual" in route.reason.lower() or "not automated" in route.reason
    assert (reply.status, reply.reason_code) == ("skipped", "generative")
    assert stream.reason_code == "streaming"
    assert GO.translate(SRC, [route], 0.85, None) == SRC  # never rewrites Go


def test_go_sashabaranov_client():
    src = textwrap.dedent('''
        package x
        import openai "github.com/sashabaranov/go-openai"
        func F(c *openai.Client, msg string) {
            c.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
                Messages: []openai.ChatCompletionMessage{{Role: "user", Content: "Is this spam? Answer yes or no. " + msg}},
            })
        }
    ''')
    [c] = GO.analyze(src, "x.go")
    assert (c.status, c.kind, c.options) == ("candidate", "noul", ["yes", "no"])


def test_go_without_sdk_import_is_ignored():
    assert GO.analyze("package x\nfunc F() { c.Chat.Completions.New(ctx, p) }\n", "x.go") == []
