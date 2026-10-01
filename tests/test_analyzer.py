import textwrap

from jevvify.analyzer import analyze_source, classify_prompt, extract_options


def analyze(src: str):
    return analyze_source(textwrap.dedent(src), "app.py")


def test_openai_classification_is_a_candidate():
    [c] = analyze('''
        from openai import OpenAI
        client = OpenAI()

        def triage(email):
            return client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Categorize as billing, technical, or other. Reply with the label only."},
                    {"role": "user", "content": f"Ticket: {email}"},
                ],
            )
    ''')
    assert c.status == "candidate" and c.kind == "choice"
    assert c.options == ["billing", "technical", "other"]
    assert c.variables == {"email": "email"}
    assert "Reply with" not in c.instructions
    assert c.provider == "openai"


def test_yes_no_question_becomes_noul():
    [c] = analyze('''
        import anthropic
        client = anthropic.Anthropic()
        def f(text):
            return client.messages.create(model="m", max_tokens=5,
                messages=[{"role": "user", "content": f"Is this spam? Answer yes or no.\\n{text}"}])
    ''')
    assert (c.status, c.kind, c.options) == ("candidate", "noul", ["yes", "no"])
    assert c.provider == "anthropic"


def test_prompt_resolved_through_local_variable():
    [c] = analyze('''
        import openai
        def f(client, body):
            prompt = f"Route to sales or support: {body}"
            return client.chat.completions.create(model="m", messages=[{"role": "user", "content": prompt}])
    ''')
    assert c.status == "candidate" and c.options == ["sales", "support"]
    assert c.variables == {"body": "body"}


def test_json_mode_is_recorded_and_key_inferred():
    [c] = analyze('''
        import openai
        def f(client, msg):
            return client.chat.completions.create(model="m", response_format={"type": "json_object"},
                messages=[{"role": "user", "content": f'Classify as urgent, normal or low. Return {{"priority": "..."}} for: {msg}'}])
    ''')
    assert c.status == "candidate" and c.json_mode and c.json_key == "priority"


def test_generative_prompt_is_skipped():
    [c] = analyze('''
        import openai
        def f(client):
            return client.chat.completions.create(model="m",
                messages=[{"role": "user", "content": "Write an essay describing a flower"}])
    ''')
    assert c.status == "skipped" and "generative" in c.reason


def test_skips_streaming_tools_and_async():
    cands = analyze('''
        import openai
        async def f(client, t):
            await client.chat.completions.create(model="m", messages=[{"role": "user", "content": f"Is it ok? {t}"}])
        def g(client, t):
            client.chat.completions.create(model="m", stream=True, messages=[{"role": "user", "content": f"Is it ok? {t}"}])
            client.chat.completions.create(model="m", tools=[{}], messages=[{"role": "user", "content": f"Is it ok? {t}"}])
    ''')
    assert [c.reason for c in cands] == ["async call (not rewritten)", "streaming call", "tool/function calling"]
    assert all(c.status == "skipped" for c in cands)


def test_constant_prompt_without_input_is_skipped():
    [c] = analyze('''
        import openai
        def f(client):
            return client.chat.completions.create(model="m", messages=[{"role": "user", "content": "Is the sky blue?"}])
    ''')
    assert c.status == "skipped" and "no dynamic input" in c.reason


def test_no_provider_import_means_no_findings():
    assert analyze('''
        def f(client, x):
            return client.chat.completions.create(messages=[{"role": "user", "content": f"Is {x} ok?"}])
    ''') == []


def test_langchain_invoke_and_format():
    [c] = analyze('''
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI()
        def f(review):
            return llm.invoke("Classify this review as positive, negative or neutral: {r}".format(r=review))
    ''')
    assert c.status == "candidate" and c.provider == "langchain"
    assert c.options == ["positive", "negative", "neutral"] and c.variables == {"review": "review"}


def test_already_rewritten_calls_are_ignored():
    assert analyze('''
        import openai
        from _jevvify_rt import route as _jevvify_route
        def f(client, t):
            return _jevvify_route("jev_1", {"t": t}, lambda: client.chat.completions.create(
                messages=[{"role": "user", "content": f"Is {t} ok?"}]), kind="noul", instructions="", options=[], shape="openai")
    ''') == []


def test_extract_options_variants():
    assert extract_options("Route to sales or support.") == ["sales", "support"]
    assert extract_options("Choose one of: a, b, c") == ["a", "b", "c"]
    assert extract_options("Categories:\n- billing: money issues\n- bug\n- other\nThanks") == ["billing", "bug", "other"]
    assert extract_options("Summarise this long thing") is None


def test_negated_explanation_is_not_generative():
    kind, options, _ = classify_prompt("Classify as safe or unsafe. Do not explain.")
    assert kind == "choice" and options == ["safe", "unsafe"]

def test_option_list_in_variable_fstring():
    [c] = analyze('''
        import openai
        CATEGORIES = ["billing", "support", "refund"]
        def f(client, text):
            return client.chat.completions.create(model="m",
                messages=[{"role": "user", "content": f"Classify the ticket. Possible categories: {CATEGORIES}. Ticket: {text}"}])
    ''')
    assert c.status == "candidate"
    assert c.options == ["billing", "support", "refund"]
    assert c.variables == {"text": "text"}


def test_option_list_in_variable_format():
    [c] = analyze('''
        import openai
        CATEGORIES = ("billing", "support", "refund")
        def f(client, text):
            return client.chat.completions.create(model="m",
                messages=[{"role": "user", "content": "Classify the ticket. Possible categories: {cats}. Ticket: {text}".format(cats=CATEGORIES, text=text)}])
    ''')
    assert c.status == "candidate"
    assert c.options == ["billing", "support", "refund"]
    assert c.variables == {"text": "text"}


def test_string_variable_in_fstring():
    [c] = analyze('''
        import openai
        CATEGORIES = "billing, support, refund"
        def f(client, text):
            return client.chat.completions.create(model="m",
                messages=[{"role": "user", "content": f"Classify as {CATEGORIES}: {text}"}])
    ''')
    assert c.status == "candidate"
    assert c.options == ["billing", "support", "refund"]
    assert c.variables == {"text": "text"}