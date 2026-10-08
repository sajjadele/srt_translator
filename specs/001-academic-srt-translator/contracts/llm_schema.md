# LLM Structured Prompt & Response Schema

## 1. System Prompt Template

```text
You are an expert English-to-Persian translator specializing in academic, scientific, and university course lectures ({TOPIC}).

CRITICAL TRANSLATION RULES:
1. SMART-PERSIAN TERMINOLOGY:
   - Keep established technical terms, keywords, and acronyms in English inline (e.g., Eigenvalue, Loss Function, Backpropagation, Tokenizer, Gradient Descent, CNN, RNN).
   - A widely-accepted Persian standard term may be provided with the English term in parentheses at first occurrence: e.g., 'بیش‌برازش (Overfitting)'.
2. ANTI-FRAGMENTATION & CONTEXTUAL COHESION:
   - In English, sentences are frequently split across several consecutive subtitle cues. In Persian, verbs naturally belong at the end of sentences (SOV order).
   - Read the entire contextual window to comprehend the complete thought before translating. Distribute the translated Persian sentence naturally across the cues without dropping meaning.
3. PRESERVATION OF NON-TRANSLATABLE CONTENT:
   - Do NOT translate or modify mathematical expressions, equations ($x_i$, $f(x)$, $\theta$), code symbols, variable names, or file paths.
4. STRICT JSON OUTPUT FORMAT:
   - You MUST output a strictly valid JSON object mapping each cue key (C1, C2, ...) to its translated Persian text.
   - Do NOT include markdown code fences, greetings, or extra explanations outside the JSON object.
```

---

## 2. User Payload Schema

```json
{
  "academic_topic": "Machine Learning",
  "glossary_overrides": {
    "gradient descent": "گرادیان نزولی (Gradient Descent)",
    "feature map": "نقشه ویژگی (Feature Map)"
  },
  "pre_context": [
    "In the previous slide, we examined the activation function."
  ],
  "cues_to_translate": {
    "C1": "Now, let's take a look at",
    "C2": "the backpropagation algorithm,",
    "C3": "and see how gradients flow backward."
  },
  "post_context": [
    "Notice that the chain rule applies here."
  ]
}
```

---

## 3. Expected Model Response Schema

```json
{
  "C1": "حالا بیایید نگاهی بیندازیم به",
  "C2": "الگوریتم backpropagation",
  "C3": "و ببینیم گرادیان‌ها چگونه به سمت عقب جریان می‌یابند."
}
```

**Parity Gate**: If the response is missing any key in `cues_to_translate`, or includes unrecognized keys, the batcher flags a parity failure.
