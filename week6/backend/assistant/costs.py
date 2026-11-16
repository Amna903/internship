"""Approximate token and cost reporting.

Tokens come from the model server's own counts after each call. The local model costs nothing per call;
the hosted-equivalent figure shows what the same tokens would cost on a typical paid API, using
ILLUSTRATIVE prices (not a quote for any provider), so the cost of moving off a local model is visible.
"""

LOCAL_COST_PER_1K = {"input": 0.0, "output": 0.0}
ILLUSTRATIVE_HOSTED_PER_1K = {"input": 0.0005, "output": 0.0015}  # USD; illustrative only


def cost_report(prompt_tokens: int, output_tokens: int) -> dict:
    def price(table):
        return round(prompt_tokens / 1000 * table["input"] + output_tokens / 1000 * table["output"], 6)

    return {
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": prompt_tokens + output_tokens,
        "cost_usd": price(LOCAL_COST_PER_1K),
        "hosted_equivalent_usd": price(ILLUSTRATIVE_HOSTED_PER_1K),
        "note": "Local model: no per-call cost. Hosted equivalent uses illustrative prices, not a quote.",
    }
