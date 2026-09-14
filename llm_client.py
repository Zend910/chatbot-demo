"""Tất cả lời gọi tới model AI đều nằm ở đây, dùng Google Gemini API (có gói
MIỄN PHÍ, không cần thẻ tín dụng — lấy key tại aistudio.google.com).
App chạy local, chỉ có traffic ra ngoài là gọi tới generativelanguage.googleapis.com
bằng API key do bạn tự cấu hình."""
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import google.generativeai as genai

from config import load_config
import retrieval

MAX_TOKENS_CHAT = 5000
MAX_TOKENS_LONG = 6000
MAX_TOKENS_VISION = 12000


def append_custom_instruction(system, custom_instructions=None):
    if not custom_instructions:
        return system
    cleaned = str(custom_instructions).strip()
    if not cleaned:
        return system
    return (
        f"{system}\n\n"
        "[HƯỚNG DẪN TÙY CHỈNH CỦA NGƯỜI DÙNG — ƯU TIÊN CAO, BẮT BUỘC ÁP DỤNG]\n"
        "Người dùng đã tự thiết lập hướng dẫn cá nhân hóa dưới đây trong phần Cài đặt. "
        "Hãy tuân thủ NGHIÊM NGẶT và NHẤT QUÁN trong toàn bộ câu trả lời (không chỉ câu mở đầu): "
        "cách xưng hô/gọi tên người dùng, giọng văn, mức độ hài hước hoặc nghiêm túc, độ dài, "
        "và bất kỳ sở thích nào khác được nêu ra — miễn là không vi phạm các nguyên tắc an toàn. "
        "Nếu hướng dẫn yêu cầu một cách gọi tên riêng cho người dùng, hãy dùng đúng cách gọi đó "
        "khi xưng hô trong câu trả lời, kể cả khi nó khác với văn phong mặc định ở trên.\n"
        "--- Hướng dẫn của người dùng ---\n"
        f"{cleaned}\n"
        "--- Hết hướng dẫn ---\n"
    )


MATH_FORMAT_INSTRUCTION = (
    "\n\nKHI GIẢI BÀI TẬP TOÁN (hoặc có phép tính số học/đại số bất kỳ), trình bày từng bước rõ ràng bằng "
    "ký hiệu quen thuộc, dễ đọc trên điện thoại: dùng đúng dấu × cho phép nhân (không dùng dấu *), dấu ÷ hoặc "
    "viết phân số dạng a/b cho phép chia, dấu +, -, = như bình thường, dùng √ cho căn bậc hai (ví dụ √16), "
    "dùng số mũ kiểu x² hoặc x³ khi cần lũy thừa, dùng ≤ ≥ ≠ ≈ π khi cần. "
    "TUYỆT ĐỐI KHÔNG dùng ký hiệu LaTeX hay Markdown gây khó hiểu (như \\times, \\frac{}{}, \\sqrt{}, "
    "\\left, \\right, dấu $ bao quanh công thức, dấu *, dấu #, dấu ^{}, dấu _{} thô) — chỉ dùng chữ, số và "
    "ký hiệu toán học thông thường ở trên, trình bày mỗi bước tính trên một dòng để học sinh dễ theo dõi."
)


class NotConfiguredError(Exception):
    pass


def _configure(runtime_config=None):
    cfg = load_config(runtime_config)
    if not cfg.get("api_key"):
        raise NotConfiguredError(
            "Chưa cấu hình Google AI API key. Vào mục Cài đặt để nhập key (miễn phí, "
            "lấy tại aistudio.google.com)."
        )
    genai.configure(api_key=cfg["api_key"])
    model_name = cfg.get("model") or "gemini-3.6-flash"
    if model_name in {"Gemini API Key 2", "gemini-2.5-flash"} or not model_name.startswith("gemini-"):
        model_name = "gemini-3.6-flash"
    return model_name


def extract_text_from_image(image, runtime_config=None):
    """Extract document text from a PIL image with Gemini Vision."""
    model_name = _configure(runtime_config)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(
        [
            (
                "Đọc toàn bộ chữ trong ảnh tài liệu này. Chỉ trả về phần văn bản đã đọc, "
                "giữ nguyên thứ tự đọc và xuống dòng hợp lý. Không thêm nhận xét, không bọc "
                "trong Markdown, không mô tả hình ảnh và không đoán phần không nhìn rõ."
            ),
            image,
        ],
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=MAX_TOKENS_VISION,
            temperature=0,
        ),
    )
    return (response.text or "").strip()


def _strip_json_fence(text):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _parse_json_object(text):
    """Parse a JSON object even when the model wraps it in Markdown fences."""
    cleaned = _strip_json_fence(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model không trả về JSON hợp lệ.")
    return json.loads(cleaned[start : end + 1])


def _post_json(url, headers, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def _openai_text(system, prompt, max_tokens, json_mode=False, runtime_config=None):
    cfg = load_config(runtime_config)
    if not cfg.get("openai_api_key"):
        raise NotConfiguredError("Chưa có OpenAI API key.")
    payload = {
        "model": cfg.get("openai_model") or "gpt-4o-mini",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {cfg['openai_api_key']}"},
        payload,
    )
    return data["choices"][0]["message"]["content"]


def _openrouter_text(system, prompt, max_tokens, json_mode=False, runtime_config=None):
    cfg = load_config(runtime_config)
    if not cfg.get("openrouter_api_key"):
        raise NotConfiguredError("Chưa có OpenRouter API key.")
    payload = {
        "model": cfg.get("openrouter_model") or "openai/gpt-4o-mini",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {
            "Authorization": f"Bearer {cfg['openrouter_api_key']}",
            "HTTP-Referer": "http://127.0.0.1:5050",
            "X-Title": "NotebookLM Clone",
        },
        payload,
    )
    return data["choices"][0]["message"]["content"]


def _anthropic_text(system, prompt, max_tokens, runtime_config=None):
    cfg = load_config(runtime_config)
    if not cfg.get("anthropic_api_key"):
        raise NotConfiguredError("Chưa có Anthropic API key.")
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": cfg["anthropic_api_key"],
            "anthropic-version": "2023-06-01",
        },
        {
            "model": cfg.get("anthropic_model") or "claude-3-5-haiku-latest",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return "".join(block.get("text", "") for block in data.get("content", []))


def _generate_with_fallback(system, prompt, max_tokens, json_mode=False, chat_history=None, runtime_config=None):
    cfg = load_config(runtime_config)
    errors = []

    preferred = cfg.get("provider", "auto")
    providers = ["gemini", "openai", "openrouter", "anthropic"]
    if preferred in providers:
        providers.remove(preferred)
        providers.insert(0, preferred)

    for provider in providers:
      if provider == "gemini" and cfg.get("api_key"):
        try:
            model_name = _configure(runtime_config)
            model = genai.GenerativeModel(model_name, system_instruction=system)
            if chat_history:
                history = [
                    {
                        "role": "user" if turn["role"] == "user" else "model",
                        "parts": [
                            turn["content"]
                            + (
                                "\n\n[NGỮ CẢNH ẢNH ĐÃ ĐÍNH KÈM Ở LƯỢT TRƯỚC]\n"
                                + turn["image_context"]
                                if turn.get("image_context")
                                else ""
                            )
                        ],
                    }
                    for turn in chat_history[-6:]
                ]
                response = model.start_chat(history=history).send_message(
                    prompt,
                    generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
                )
            else:
                if json_mode:
                    generation_config = genai.types.GenerationConfig(
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                    )
                else:
                    generation_config = genai.types.GenerationConfig(max_output_tokens=max_tokens)
                response = model.generate_content(prompt, generation_config=generation_config)
            return response.text
        except Exception as exc:
            errors.append(f"Gemini: {exc}")
      elif provider == "openai" and cfg.get("openai_api_key"):
        try:
            return _openai_text(system, prompt, max_tokens, json_mode=json_mode, runtime_config=runtime_config)
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")
      elif provider == "openrouter" and cfg.get("openrouter_api_key"):
        try:
            return _openrouter_text(system, prompt, max_tokens, json_mode=json_mode, runtime_config=runtime_config)
        except Exception as exc:
            errors.append(f"OpenRouter: {exc}")
      elif provider == "anthropic" and cfg.get("anthropic_api_key"):
        try:
            return _anthropic_text(system, prompt, max_tokens, runtime_config=runtime_config)
        except Exception as exc:
            errors.append(f"Anthropic: {exc}")

    if errors:
        raise RuntimeError(
            "Gemini hết hạn mức hoặc gặp lỗi và chưa gọi được AI dự phòng. "
            "Hãy kiểm tra API key OpenAI/Anthropic trong Cài đặt."
        ) from RuntimeError("; ".join(errors))
    raise NotConfiguredError("Chưa cấu hình API key Gemini, OpenAI hoặc Anthropic.")


def answer_question(retrieved_chunks, question, chat_history, custom_instructions=None, runtime_config=None):
    """retrieved_chunks: list[{chunk_id, text, position, doc_id, doc_name}]
    Trả về {"answer": str, "citations": [{"marker": "1", "doc_name", "position", "snippet"}]}
    """
    numbered = []
    citation_map = {}
    for i, c in enumerate(retrieved_chunks, start=1):
        numbered.append(f"[{i}] (Nguồn: {c['doc_name']}, {c['position']})\n{c['text']}")
        citation_map[str(i)] = {
            "marker": str(i),
            "doc_name": c["doc_name"],
            "position": c["position"],
            "snippet": c["text"][:220],
        }
    context_block = "\n\n".join(numbered) if numbered else "(Không có tài liệu nào được tải lên)"
    recent_image_context = next(
        (turn.get("image_context", "") for turn in reversed(chat_history or []) if turn.get("image_context")),
        "",
    )
    image_history_block = (
        "\n\nNGỮ CẢNH ẢNH TỪ LƯỢT TRƯỚC (được phép dùng khi câu hỏi hiện tại liên quan):\n"
        + recent_image_context[:20000]
        if recent_image_context
        else ""
    )

    system = append_custom_instruction(
        "Bạn là trợ lý nghiên cứu thân thiện, trả lời tự nhiên như một gia sư đang giải thích cho học sinh. "
        "Với câu hỏi yêu cầu giải thích, tóm tắt hoặc hướng dẫn, hãy trả lời đầy đủ khoảng 300-600 từ "
        "hoặc 5-8 đoạn có nội dung, gồm ý chính, giải thích, ví dụ trong tài liệu và kết luận khi phù hợp. "
        "Với câu hỏi thực tế rất ngắn, trả lời ngắn vừa đủ; không kéo dài bằng cách lặp ý. "
        "Chỉ chia thành vài phần khi thật sự cần; tránh văn phong máy móc và tránh lặp lại đề bài. "
        "Chỉ dùng thông tin trong các đoạn nguồn, nhưng nếu nguồn có đủ dữ kiện thì phải tổng hợp và giải thích, "
        "không được chỉ nói 'không tìm thấy'. Nếu câu hỏi mơ hồ, hãy nêu cách hiểu hợp lý rồi trả lời phần có thể. "
        "Khi dùng thông tin từ nguồn, chèn số [1], [2]... ngay sau ý tương ứng. "
        "Các số này phải khớp với nhãn Nguồn bên dưới. Viết bằng tiếng Việt; dùng gạch đầu dòng cho danh sách, "
        "dùng bảng Markdown chỉ khi cần so sánh nhiều mục, không lạm dụng tiêu đề hay bảng."
        + MATH_FORMAT_INSTRUCTION
        + f"\n\nCÁC ĐOẠN NGUỒN:\n{context_block}"
        + image_history_block,
        custom_instructions,
    )

    answer = _generate_with_fallback(
        system, question, MAX_TOKENS_CHAT, chat_history=chat_history, runtime_config=runtime_config
    )

    used_markers = sorted(set(re.findall(r"\[(\d+)\]", answer)), key=int)
    citations = [citation_map[m] for m in used_markers if m in citation_map]

    return {"answer": answer, "citations": citations}


def answer_question_with_image(image_context, question, chat_history, custom_instructions=None, runtime_config=None):
    """Trả lời câu hỏi khi người dùng DÁN ảnh trực tiếp vào khung chat (Ctrl+V)
    kèm theo câu hỏi. image_context là văn bản đã nhận diện (OCR) từ (các) ảnh
    vừa dán — ảnh này chỉ dùng nhất thời cho câu hỏi hiện tại, KHÔNG được lưu
    thành nguồn/tài liệu trong Sổ tay. Vì vậy câu trả lời phải tập trung vào nội
    dung ảnh + câu hỏi, không được tìm/trích dẫn các tài liệu khác đã tải lên.
    Trả về {"answer": str, "citations": []} (không có trích dẫn vì không dùng nguồn).
    """
    system = append_custom_instruction(
        "Bạn là trợ lý AI thân thiện. Người dùng vừa DÁN (các) ảnh trực tiếp vào khung chat, ngay kèm theo "
        "câu hỏi bên dưới — đây là một câu hỏi riêng, tức thời về (các) ảnh này, không liên quan tới các "
        "tài liệu/nguồn khác đã có sẵn trong Sổ tay. Nội dung chữ trong (các) ảnh (đã được nhận diện bằng OCR) "
        "được cung cấp ngay dưới đây. HÃY TẬP TRUNG HOÀN TOÀN trả lời dựa trên nội dung ảnh này và câu hỏi của "
        "người dùng: nếu ảnh là đề bài/bài tập thì giải chi tiết; nếu là văn bản/hình ảnh thông tin thì tóm tắt, "
        "giải thích hoặc trả lời đúng theo yêu cầu. TUYỆT ĐỐI KHÔNG chèn số trích dẫn kiểu [1], [2], không nhắc "
        "tới hay dựa vào các tài liệu khác đã tải lên Sổ tay — chỉ dùng nội dung ảnh vừa dán. Trả lời tự nhiên, "
        "đầy đủ, rõ ràng, viết bằng tiếng Việt."
        + MATH_FORMAT_INSTRUCTION
        + f"\n\nNỘI DUNG NHẬN DIỆN ĐƯỢC TỪ (CÁC) ẢNH VỪA DÁN:\n{image_context}",
        custom_instructions,
    )

    answer = _generate_with_fallback(
        system, question, MAX_TOKENS_CHAT, chat_history=chat_history, runtime_config=runtime_config
    )

    return {"answer": answer, "citations": []}


def summarize_documents(documents, custom_instructions=None, runtime_config=None):
    """documents: list[{name, chunks}] -> tóm tắt tổng hợp dạng markdown."""
    doc_blocks = []
    for doc in documents:
        full_text = " ".join(c["text"] for c in doc["chunks"])[:18000]
        doc_blocks.append(f"### Tài liệu: {doc['name']}\n{full_text}")
    combined = "\n\n".join(doc_blocks)

    system = append_custom_instruction(
        "Bạn là trợ lý nghiên cứu đang viết bản tóm tắt đầy đủ bằng tiếng Việt, không phải bản tóm tắt vài dòng.\n"
        "Hãy trình bày có cấu trúc Markdown:\n"
        "1. Tổng quan: 1-2 đoạn, nêu chủ đề, mục tiêu và phạm vi.\n"
        "2. Các ý chính: chia theo chủ đề/chương, giải thích mỗi ý bằng vài câu.\n"
        "3. Khái niệm, ví dụ hoặc quy trình quan trọng trong tài liệu.\n"
        "4. Kết luận và điều người đọc cần nhớ.\n"
        "Nếu tài liệu dài, hãy ưu tiên nội dung bài học và kiến thức cốt lõi thay vì chỉ mô tả mục lục.",
        custom_instructions,
    )

    return _generate_with_fallback(system, combined, MAX_TOKENS_LONG, runtime_config=runtime_config)


def generate_quiz(documents, n_questions=6, difficulty="medium", topic="", custom_instructions=None, runtime_config=None):
    source_chunks = retrieval.topic_chunks(documents, topic, limit=50) if topic else [
        {**chunk, "doc_name": doc["name"], "doc_id": doc["id"]}
        for doc in documents
        for chunk in doc["chunks"]
    ]
    doc_blocks = []
    grouped = {}
    for chunk in source_chunks:
        grouped.setdefault(chunk["doc_name"], []).append(chunk["text"])
    for name, texts in grouped.items():
        doc_blocks.append(f"### {name}\n" + " ".join(texts)[:14000])
    combined = "\n\n".join(doc_blocks)

    difficulty_labels = {"easy": "dễ", "medium": "trung bình", "hard": "khó"}
    difficulty_label = difficulty_labels.get(difficulty, "trung bình")
    topic_instruction = (
        f"Chỉ tập trung vào chủ đề người dùng yêu cầu: {topic}. "
        "Nếu chủ đề là một bài/chương, chỉ lấy kiến thức thuộc bài/chương đó; "
        "không lấy câu hỏi từ phần khác.\n"
        if topic else
        "Bao quát các nội dung chính trong những tài liệu đã chọn.\n"
    )
    system = append_custom_instruction(
        f"Dựa CHỈ trên phần nội dung đã lọc bên dưới, tạo {n_questions} câu hỏi trắc nghiệm bằng tiếng Việt "
        f"ở mức độ {difficulty_label}. "
        + topic_instruction
        + ("TUYỆT ĐỐI không lấy kiến thức ngoài phạm vi chủ đề này. Nếu dữ liệu không đủ, hãy tạo ít câu hơn thay vì lấy sang bài khác.\n" if topic else "")
        + "để ôn tập kiến thức. Mỗi câu có 4 lựa chọn, chỉ 1 đáp án đúng, giải thích tối đa 12 từ. "
        + "Câu hỏi và lựa chọn phải ngắn gọn để trả về đủ số lượng.\n"
        + "CHỈ trả về JSON hợp lệ, không thêm chữ nào khác, theo đúng cấu trúc:\n"
        + '{"questions": [{"question": "...", "options": ["A","B","C","D"], '
        + '"correct_index": 0, "explanation": "..."}]}'
        + MATH_FORMAT_INSTRUCTION
        , custom_instructions
    )

    raw = _generate_with_fallback(
        system,
        combined,
        max(MAX_TOKENS_LONG, n_questions * 650),
        json_mode=True,
        runtime_config=runtime_config,
    )
    data = _parse_json_object(raw)
    return data.get("questions", [])


def _topic_source(documents, topic, limit=50):
    chunks = retrieval.topic_chunks(documents, topic, limit=limit) if topic else [
        {**chunk, "doc_name": doc["name"], "doc_id": doc["id"]}
        for doc in documents
        for chunk in doc["chunks"]
    ]
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk["doc_name"], []).append(chunk["text"])
    return "\n\n".join(
        f"### {name}\n{' '.join(texts)[:16000]}" for name, texts in grouped.items()
    )


def generate_mindmap(documents, topic="", custom_instructions=None, runtime_config=None):
    combined = _topic_source(documents, topic, limit=60)
    scope = f"Chủ đề bắt buộc: {topic}." if topic else "Bao quát nội dung chính."
    system = append_custom_instruction(
        "Tạo mind map học tập bằng tiếng Việt dựa CHỈ trên nội dung đã cung cấp. "
        f"{scope} Không lấy kiến thức ngoài phạm vi topic. "
        "Trả về JSON hợp lệ, không Markdown, theo cấu trúc: "
        '{"title":"...","summary":"...","nodes":[{"title":"...",'
        '"summary":"...","children":[{"title":"...","summary":"..."}]}]}. '
        "Tạo 3-7 nhánh chính, mỗi nhánh 2-5 ý con, diễn đạt ngắn gọn nhưng có ý nghĩa.",
        custom_instructions,
    )
    raw = _generate_with_fallback(system, combined, MAX_TOKENS_LONG, json_mode=True, runtime_config=runtime_config)
    return _parse_json_object(raw)


def generate_flashcards(documents, n_cards=10, topic="", custom_instructions=None, runtime_config=None):
    combined = _topic_source(documents, topic, limit=50)
    scope = f"Chỉ tập trung vào chủ đề: {topic}." if topic else "Bao quát nội dung chính."
    system = append_custom_instruction(
        f"Tạo {n_cards} flashcard học tập bằng tiếng Việt dựa CHỈ trên nội dung đã cung cấp. "
        f"{scope} Nếu topic là Bài/Chương, tuyệt đối không lấy nội dung bài khác. "
        "Trả về JSON hợp lệ, không Markdown, theo cấu trúc: "
        '{"cards":[{"front":"câu hỏi hoặc khái niệm",'
        '"back":"câu trả lời rõ ràng, có thể kèm ví dụ", "hint":"gợi ý ngắn"}]}. '
        "Mỗi mặt trước chỉ hỏi một ý; mặt sau dài 1-4 câu, chính xác và dễ học."
        + MATH_FORMAT_INSTRUCTION,
        custom_instructions,
    )
    raw = _generate_with_fallback(system, combined, max(MAX_TOKENS_LONG, n_cards * 350), json_mode=True, runtime_config=runtime_config)
    return _parse_json_object(raw).get("cards", [])


def generate_podcast_script(documents, style_note="", custom_instructions=None, runtime_config=None):
    """Trả về list[{"speaker": "A"|"B", "text": "..."}] mô phỏng 2 người dẫn thảo luận."""
    doc_blocks = []
    for doc in documents:
        full_text = " ".join(c["text"] for c in doc["chunks"])[:6000]
        doc_blocks.append(f"### {doc['name']}\n{full_text}")
    combined = "\n\n".join(doc_blocks)

    system = append_custom_instruction(
        "Bạn viết kịch bản podcast tiếng Việt, hai người dẫn chương trình (A và B) trò chuyện "
        "tự nhiên, dễ hiểu, để tóm tắt và thảo luận nội dung tài liệu được cung cấp cho người "
        "nghe chưa biết gì về tài liệu. Giọng điệu thân thiện, có hỏi-đáp qua lại, khoảng "
        "12-18 lượt thoại, mỗi lượt 1-3 câu. " + style_note + "\n"
        "CHỈ trả về JSON hợp lệ theo cấu trúc: "
        '{"turns": [{"speaker": "A", "text": "..."}, {"speaker": "B", "text": "..."}]}'
        , custom_instructions
    )

    raw = _generate_with_fallback(system, combined, MAX_TOKENS_LONG, json_mode=True, runtime_config=runtime_config)
    data = _parse_json_object(raw)
    return data.get("turns", [])
