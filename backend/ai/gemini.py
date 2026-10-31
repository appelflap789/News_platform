"""Google's Gemini API, used for one thing: writing out what is said, in a public YouTube video or in the audio
file of a podcast episode.

Why this and not YouTube's own API: the YouTube Data API gives a video's transcript only to someone who may
edit that video. Reading it off YouTube's player instead is against YouTube's terms and its robots.txt, and
the platform does not do that. Gemini is Google's own way in: it is handed the address of a public video and
answers with text. It needs a Gemini API key (Settings); while the feature is in preview, Google does not
charge for it, and the free tier reads at most eight hours of video a day.

A podcast episode is not on YouTube, so its audio file (the one the show's own feed offers) is handed over
instead: uploaded to Google's Files API, read, and deleted again at once. Google keeps an uploaded file for at
most 48 hours in any case, and does not charge for the Files API.

The request and the answer follow the Interactions API as documented in October 2026
(https://ai.google.dev/gemini-api/docs/video-understanding, .../audio and .../files).
"""

from __future__ import annotations

import os
import time

import requests

from .. import config
from ..jobs import JobError

BASE = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 900  # seconds; a two-hour video takes minutes to read
PROMPT = (
    "Write out what is said in this video, as a transcript in the language that is spoken.\n"
    "- Start a new paragraph whenever the subject or the speaker changes, and begin every paragraph with the "
    "time it starts at, as [MM:SS] (or [H:MM:SS] after the first hour).\n"
    "- When more than one person speaks, name the speaker after the time, if the video makes clear who it is.\n"
    "- Keep the speakers' own words. Do not summarise, comment, translate or add anything, and leave out "
    "filler such as 'um'.\n"
    "- Text that is only shown on screen and matters for following the argument (a figure, a name on a map) "
    "may be added in (round brackets).\n"
    "- If nothing is said in the video, describe in a few sentences what it shows.\n"
    "Answer with the transcript only."
)
AUDIO_PROMPT = (
    "Write out what is said in this recording, as a transcript in the language that is spoken.\n"
    "- Start a new paragraph whenever the subject or the speaker changes, and begin every paragraph with the "
    "time it starts at, as [MM:SS] (or [H:MM:SS] after the first hour).\n"
    "- When more than one person speaks, name the speaker after the time, if the recording makes clear who it "
    "is.\n"
    "- Keep the speakers' own words. Do not summarise, comment, translate or add anything, and leave out "
    "filler such as 'um'.\n"
    "- Leave out advertisements and sponsor messages; write [advertisement] where one was.\n"
    "- If nothing is said in the recording, say so in one sentence.\n"
    "Answer with the transcript only."
)
# What a feed calls its audio -> what Gemini calls it. Nearly every podcast is an MP3.
AUDIO_TYPES = {"audio/mpeg": "audio/mp3", "audio/mp3": "audio/mp3", "audio/x-m4a": "audio/m4a", "audio/mp4": "audio/m4a",
               "audio/m4a": "audio/m4a", "audio/aac": "audio/aac", "audio/ogg": "audio/ogg", "audio/wav": "audio/wav",
               "audio/x-wav": "audio/wav", "audio/flac": "audio/flac"}


class GeminiError(JobError):
    """Gemini could not write out a video; the message is written for the user."""


class TryLater(GeminiError):
    """Nothing is wrong with this video: the day's allowance is used up, or the service is busy."""


class Misconfigured(GeminiError):
    """No video will work until a setting is put right: the key, or the name of the model."""


def available() -> bool:
    return bool(config.other_key("gemini"))


def _base() -> str:
    return os.environ.get("GEMINI_BASE_URL") or BASE  # the tests point this at a server of their own


def _key() -> str:
    key = config.other_key("gemini")
    if not key:
        raise Misconfigured("No Gemini API key yet. Add one on the Settings page to have videos and podcast "
                            "episodes written out.")
    return key


def _answer(response: requests.Response, what: str, model: str = "") -> dict:
    """The JSON of an answer from Google, or the error it stands for, said for the user. `what` is the thing
    being read: 'this video', 'this recording'."""
    try:
        answer = response.json()
    except ValueError:
        answer = {}
    if response.status_code >= 400:
        said = answer.get("error", {}) if isinstance(answer.get("error"), dict) else {}
        message = said.get("message") or response.reason or "no explanation given"
        if response.status_code == 429 or response.status_code >= 500:
            raise TryLater(f"Gemini cannot take more right now (HTTP {response.status_code}: {message}).")
        if response.status_code in (401, 403):
            raise Misconfigured(f"The Gemini API key was not accepted (HTTP {response.status_code}: {message}). "
                                f"Check it on the Settings page.")
        if response.status_code == 404 and model:
            raise Misconfigured(f"Gemini does not know the model '{model}' (Settings, Videos).")
        raise GeminiError(f"Gemini could not read {what} (HTTP {response.status_code}: {message}).")
    return answer


def _ask(key: str, what: str, *given: dict) -> tuple[str, dict]:
    """One request to the Interactions API: the text it answers with, and the tokens it took."""
    model = str(config.get("gemini_model"))
    body = {"model": model, "input": list(given), "generation_config": {"max_output_tokens": 65000}, "store": False}
    try:
        response = requests.post(f"{_base()}/interactions", json=body, timeout=TIMEOUT,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    except requests.RequestException as error:
        raise TryLater(f"Could not reach the Gemini API ({type(error).__name__}).") from None
    answer = _answer(response, what, model)
    if answer.get("status") not in (None, "completed"):
        errors = "; ".join(str(entry.get("message", "")) for entry in answer.get("errors") or [])
        raise GeminiError(f"Gemini did not finish {what} ({answer.get('status')}{': ' + errors if errors else ''}).")
    text = "\n".join(part.get("text", "") for step in answer.get("steps") or [] if step.get("type") == "model_output"
                     for part in step.get("content") or [] if part.get("type") == "text").strip()
    if not text:
        raise GeminiError(f"Gemini returned no text for {what}.")
    usage = answer.get("usage") or {}
    return text, {"input_tokens": usage.get("total_input_tokens", 0), "output_tokens": usage.get("total_output_tokens", 0)}


def transcribe(video_url: str) -> tuple[str, dict]:
    """What is said in a public YouTube video, and how many tokens reading it took."""
    return _ask(_key(), "this video", {"type": "text", "text": PROMPT}, {"type": "video", "uri": video_url})


def transcribe_audio(content: bytes, content_type: str = "audio/mpeg", name: str = "episode") -> tuple[str, dict]:
    """What is said in an audio file (a podcast episode), and how many tokens reading it took. The file is
    uploaded for the one request and deleted afterwards, whatever the request came to."""
    key = _key()
    kind = AUDIO_TYPES.get(content_type.split(";")[0].strip().lower(), "audio/mp3")
    uploaded = _upload(key, content, kind, name)
    try:
        return _ask(key, "this recording", {"type": "text", "text": AUDIO_PROMPT},
                    {"type": "audio", "uri": uploaded["uri"], "mime_type": kind})
    finally:
        try:
            requests.delete(f"{_base()}/{uploaded['name']}", headers={"x-goog-api-key": key}, timeout=30)
        except requests.RequestException:
            pass  # Google deletes it by itself within 48 hours


def _upload(key: str, content: bytes, kind: str, name: str) -> dict:
    """Hand a file to the Files API (in its two steps) and wait until it can be read. Returns its name and uri."""
    try:
        start = requests.post(
            f"{_base().replace('/v1beta', '/upload/v1beta', 1)}/files", json={"file": {"display_name": name[:100]}},
            timeout=60, headers={
                "x-goog-api-key": key, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(content)), "X-Goog-Upload-Header-Content-Type": kind,
                "Content-Type": "application/json"})
        _answer(start, "this recording")
        target = start.headers.get("x-goog-upload-url")
        if not target:
            raise GeminiError("Gemini did not say where to upload the recording.")
        done = requests.post(target, data=content, timeout=TIMEOUT, headers={
            "Content-Length": str(len(content)), "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize"})
        uploaded = _answer(done, "this recording").get("file") or {}
        for _ in range(90):  # a long recording is not ready the moment it has arrived
            if uploaded.get("state") in (None, "ACTIVE"):
                break
            if uploaded.get("state") == "FAILED":
                raise GeminiError("Gemini could not take in the recording after it was uploaded.")
            time.sleep(2)
            asked = _answer(requests.get(f"{_base()}/{uploaded['name']}", headers={"x-goog-api-key": key},
                                         timeout=30), "this recording")
            uploaded = asked.get("file") or asked
    except requests.RequestException as error:
        raise TryLater(f"Could not reach the Gemini API to upload the recording ({type(error).__name__}).") from None
    if not uploaded.get("uri") or not uploaded.get("name"):
        raise GeminiError("Gemini did not confirm the upload of the recording.")
    return uploaded
