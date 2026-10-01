// Package spamfilter checks signup bios with the OpenAI Go SDK.
// jevvify detects Go decisions but does not rewrite Go automatically yet.
package spamfilter

import (
	"context"
	"fmt"
	"strings"

	"github.com/openai/openai-go"
)

// IsSpam is a yes/no decision: reported by jevvify as a manual candidate.
func IsSpam(ctx context.Context, client openai.Client, bio string) (bool, error) {
	prompt := fmt.Sprintf("Is this user bio spam or advertising? Answer yes or no.\n\nBio: %s", bio)
	resp, err := client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
		Model:    openai.ChatModelGPT4oMini,
		Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage(prompt)},
	})
	if err != nil {
		return false, err
	}
	return strings.HasPrefix(strings.ToLower(resp.Choices[0].Message.Content), "yes"), nil
}

// Welcome is generative and stays on the LLM.
func Welcome(ctx context.Context, client openai.Client, name string) (string, error) {
	resp, err := client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
		Model:    openai.ChatModelGPT4oMini,
		Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage("Write a one-line welcome message for " + name)},
	})
	if err != nil {
		return "", err
	}
	return resp.Choices[0].Message.Content, nil
}
