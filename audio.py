"""Tạo audio overview (dạng podcast 2 người dẫn) bằng TTS offline (pyttsx3).
Chất lượng giọng phụ thuộc vào các voice TTS có sẵn trên máy bạn. Nếu máy có
từ 2 voice trở lên, mỗi người dẫn A/B sẽ dùng 1 voice khác nhau; nếu chỉ có
1 voice, sẽ dùng tốc độ đọc khác nhau để phân biệt."""
import os
import uuid
import wave

import pyttsx3


def _pick_voices(engine):
    voices = engine.getProperty("voices")
    if len(voices) >= 2:
        return voices[0].id, voices[1].id
    if len(voices) == 1:
        return voices[0].id, voices[0].id
    return None, None


def _concat_wavs(paths, output_path):
    with wave.open(paths[0], "rb") as first:
        params = first.getparams()

    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for p in paths:
            with wave.open(p, "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def generate_podcast_audio(turns, output_dir, notebook_id):
    """turns: list[{"speaker": "A"|"B", "text": str}]. Trả về đường dẫn file wav."""
    if not turns:
        raise ValueError("Không có nội dung kịch bản để tạo audio.")

    tmp_dir = os.path.join(output_dir, f"tmp_{uuid.uuid4().hex[:6]}")
    os.makedirs(tmp_dir, exist_ok=True)

    engine = pyttsx3.init()
    voice_a, voice_b = _pick_voices(engine)
    base_rate = engine.getProperty("rate")

    segment_paths = []
    try:
        for i, turn in enumerate(turns):
            speaker = turn.get("speaker", "A")
            text = turn.get("text", "").strip()
            if not text:
                continue
            if voice_a and voice_b and voice_a != voice_b:
                engine.setProperty("voice", voice_a if speaker == "A" else voice_b)
                engine.setProperty("rate", base_rate)
            else:
                if voice_a:
                    engine.setProperty("voice", voice_a)
                engine.setProperty(
                    "rate", base_rate if speaker == "A" else max(120, base_rate - 25)
                )

            seg_path = os.path.join(tmp_dir, f"seg_{i:03d}.wav")
            engine.save_to_file(text, seg_path)
            engine.runAndWait()
            if os.path.exists(seg_path):
                segment_paths.append(seg_path)

        if not segment_paths:
            raise RuntimeError("TTS không tạo được đoạn âm thanh nào.")

        final_name = f"{notebook_id}_{uuid.uuid4().hex[:6]}.wav"
        final_path = os.path.join(output_dir, final_name)
        _concat_wavs(segment_paths, final_path)
        return final_path
    finally:
        for p in segment_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
