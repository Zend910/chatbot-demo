"""Truy hồi đoạn văn liên quan bằng TF-IDF + cosine similarity (chạy hoàn toàn local,
không cần gọi API embedding nào)."""
import re
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _page_number(chunk):
    match = re.search(r"Trang\s+(\d+)", chunk.get("position", ""))
    return int(match.group(1)) if match else None


def topic_chunks(documents, topic, limit=40):
    """Return the bounded lesson/chapter section matching a user topic."""
    normalized_topic = _normalize(topic)
    lesson = re.search(r"\b(?:bai|chuong|muc)\s*(\d+)\b", normalized_topic)
    all_chunks = [
        {**chunk, "doc_name": doc["name"], "doc_id": doc["id"]}
        for doc in documents
        for chunk in doc["chunks"]
    ]
    if not lesson:
        return top_chunks(all_chunks, topic, min(limit, len(all_chunks)))

    number = int(lesson.group(1))
    marker = re.compile(rf"\b(?:bai|chuong|muc)\s*{number}\b")
    next_marker = re.compile(rf"\b(?:bai|chuong|muc)\s*{number + 1}\b")
    selected = []
    for doc in documents:
        chunks = [
            {**chunk, "doc_name": doc["name"], "doc_id": doc["id"]}
            for chunk in doc["chunks"]
        ]
        normalized = [_normalize(chunk["text"]) for chunk in chunks]
        starts = [
            _page_number(chunk)
            for chunk, text in zip(chunks, normalized)
            if marker.search(text)
            and _page_number(chunk) is not None
            and _page_number(chunk) >= 7
            and "muc luc" not in text
            and "chu de" not in text[:250]
        ]
        if not starts:
            starts = [
                _page_number(chunk)
                for chunk, text in zip(chunks, normalized)
                if marker.search(text) and _page_number(chunk) is not None and _page_number(chunk) >= 7
            ]
        starts = [page for page in starts if page is not None]
        if not starts:
            continue
        start_page = min(starts)
        ends = [
            _page_number(chunk)
            for chunk, text in zip(chunks, normalized)
            if next_marker.search(text) and _page_number(chunk) is not None and _page_number(chunk) > start_page
        ]
        end_page = min(ends) if ends else start_page + 12
        section = [
            chunk for chunk in chunks
            if _page_number(chunk) is not None and start_page <= _page_number(chunk) < end_page
        ]
        selected.extend(section)

    if selected:
        return selected[:limit]
    return top_chunks(all_chunks, topic, min(limit, len(all_chunks)))


def top_chunks(chunks, query, k=6):
    """chunks: list[{chunk_id, text, position, doc_id, doc_name}]"""
    if not chunks:
        return []
    if len(chunks) <= k:
        return chunks

    normalized_query = _normalize(query)
    texts = [c["text"] for c in chunks]
    normalized_texts = [_normalize(text) for text in texts]

    # OCR sách giáo khoa thường làm sai dấu; ưu tiên đúng phần khi người dùng
    # hỏi theo số bài/chương thay vì để các trang mục lục chiếm kết quả.
    lesson_match = re.search(r"\b(?:bai|chuong|muc)\s*(\d+)\b", normalized_query)
    if lesson_match:
        lesson_number = lesson_match.group(1)
        marker = re.compile(rf"\b(?:bai|chuong|muc)\s*{lesson_number}\b")
        direct_hits = [chunk for chunk, text in zip(chunks, normalized_texts) if marker.search(text)]
        if direct_hits:
            remaining = [chunk for chunk in chunks if chunk not in direct_hits]
            k_direct = min(k, len(direct_hits))
            return direct_hits[:k_direct] + top_chunks(remaining, query, k - k_direct)

    vectorizer = TfidfVectorizer(
        max_df=0.95, min_df=1, ngram_range=(1, 2), sublinear_tf=True
    )
    try:
        matrix = vectorizer.fit_transform(normalized_texts + [normalized_query])
    except ValueError:
        # Từ vựng rỗng (VD tài liệu toàn số/ký hiệu) -> trả về k đoạn đầu
        return chunks[:k]

    doc_vectors = matrix[:-1]
    query_vector = matrix[-1]
    scores = cosine_similarity(query_vector, doc_vectors)[0]

    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    return [c for score, c in ranked[:k] if score > 0] or chunks[:k]
