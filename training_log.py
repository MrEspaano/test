#!/usr/bin/env python3
"""
Minimal personal training log app.
Single-file design with clear class boundaries so logic is easy to refactor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Dict
import csv
import itertools
import json

from flask import Flask, request, redirect, url_for, render_template_string, send_file


# Domain model: keep data shapes simple and explicit.
@dataclass
class Session:
    id: int
    date: date
    activity_type: str
    duration_minutes: int
    intensity: int  # 1-10

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "activity_type": self.activity_type,
            "duration_minutes": self.duration_minutes,
            "intensity": self.intensity,
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Session":
        return Session(
            id=int(data["id"]),
            date=date.fromisoformat(str(data["date"])),
            activity_type=str(data["activity_type"]),
            duration_minutes=int(data["duration_minutes"]),
            intensity=int(data["intensity"]),
        )


# Reflection question structure for better traceability and future analytics.
@dataclass
class ReflectionItem:
    question_text: str
    reason: str  # "base", "high_intensity", "trend"
    answer: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "question_text": self.question_text,
            "reason": self.reason,
            "answer": self.answer,
        }

    @staticmethod
    def from_dict(data: Dict[str, str]) -> "ReflectionItem":
        return ReflectionItem(
            question_text=str(data["question_text"]),
            reason=str(data["reason"]),
            answer=str(data.get("answer", "")),
        )


# Domain model for reflections; separate from Session to keep concerns isolated.
@dataclass
class Reflection:
    session_id: int
    items: List[ReflectionItem]
    trigger_type: str  # "system" or "manual"

    def to_dict(self) -> Dict[str, object]:
        return {
            "session_id": self.session_id,
            "items": [item.to_dict() for item in self.items],
            "trigger_type": self.trigger_type,
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "Reflection":
        # Backward-compatible load if old fields exist.
        if "items" not in data and "questions" in data:
            questions = list(data.get("questions", []))
            answers = list(data.get("answers", []))
            items = [
                ReflectionItem(
                    question_text=str(q),
                    reason="base",
                    answer=str(answers[i]) if i < len(answers) else "",
                )
                for i, q in enumerate(questions)
            ]
        else:
            items = [ReflectionItem.from_dict(d) for d in data.get("items", [])]

        return Reflection(
            session_id=int(data["session_id"]),
            items=items,
            trigger_type=str(data["trigger_type"]),
        )


# Engine layer: generates reflection prompts based on rules.
class ReflectionEngine:
    BASE_QUESTIONS = [
        "Vad gick bra under passet?",
        "Vad kan förbättras nästa gång?",
        "Hur kändes kroppen under och efter passet?",
    ]
    EXTRA_INTENSITY_QUESTION = "Vad hjälpte dig att hantera den höga ansträngningen?"

    def generate(self, session: Session, trigger_type: str) -> Reflection:
        if trigger_type not in {"system", "manual"}:
            raise ValueError("trigger_type must be 'system' or 'manual'")

        items = [ReflectionItem(question_text=q, reason="base") for q in self.BASE_QUESTIONS]
        if session.intensity >= 8:
            items.append(ReflectionItem(question_text=self.EXTRA_INTENSITY_QUESTION, reason="high_intensity"))

        return Reflection(
            session_id=session.id,
            items=items,
            trigger_type=trigger_type,
        )


@dataclass
class Conclusion:
    supportive_text: str
    direct_text: str


class AnalysisRule:
    def evaluate(self, sessions: List[Session]) -> Conclusion | None:
        raise NotImplementedError


# Rule: high average load across the last three sessions.
class HighRecentLoadRule(AnalysisRule):
    def evaluate(self, sessions: List[Session]) -> Conclusion | None:
        last_three = sessions[-3:]
        avg_intensity = sum(s.intensity for s in last_three) / 3
        if avg_intensity <= 7:
            return None

        return Conclusion(
            supportive_text=(
                "Dina tre senaste pass har varit ganska intensiva i snitt. "
                "Överväg en lättare dag eller extra återhämtning för att hålla i längden."
            ),
            direct_text=(
                "Genomsnittlig ansträngning över de tre senaste passen är hög. "
                "Planera in återhämtning eller lägre intensitet snart."
            ),
        )


# Analysis layer: computes summary insights from recent sessions only.
class AnalysisEngine:
    def __init__(self) -> None:
        # Rules are explicit so future additions stay simple and testable.
        self._rules: List[AnalysisRule] = [HighRecentLoadRule()]

    def analyze(self, sessions: List[Session], language_mode: str) -> str:
        if language_mode not in {"supportive", "direct"}:
            raise ValueError("language_mode must be 'supportive' or 'direct'")

        if len(sessions) < 3:
            return "Inte tillräckligt med pass för analys ännu (behöver 3)."

        conclusions = []
        for rule in self._rules:
            conclusion = rule.evaluate(sessions)
            if conclusion:
                conclusions.append(conclusion)

        if not conclusions:
            return "Ansträngningen ser balanserad ut över de tre senaste passen."

        if language_mode == "supportive":
            return "\n".join(c.supportive_text for c in conclusions)
        return "\n".join(c.direct_text for c in conclusions)


# Export layer: transforms stored data into CSV output.
class Exporter:
    def export_csv(self, sessions: List[Session], reflections: List[Reflection], path: str) -> None:
        reflections_by_session: Dict[int, Reflection] = {r.session_id: r for r in reflections}

        # Flatten answers into a single string so each session is one row.
        fieldnames = [
            "id",
            "date",
            "activity_type",
            "duration_minutes",
            "intensity",
            "reflection_trigger_type",
            "reflection_questions",
            "reflection_reasons",
            "reflection_answers",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in sessions:
                reflection = reflections_by_session.get(s.id)
                items = reflection.items if reflection else []
                writer.writerow(
                    {
                        "id": s.id,
                        "date": s.date.isoformat(),
                        "activity_type": s.activity_type,
                        "duration_minutes": s.duration_minutes,
                        "intensity": s.intensity,
                        "reflection_trigger_type": reflection.trigger_type if reflection else "",
                        "reflection_questions": " | ".join(item.question_text for item in items),
                        "reflection_reasons": " | ".join(item.reason for item in items),
                        "reflection_answers": " | ".join(item.answer for item in items),
                    }
                )


@dataclass
class AppConfig:
    analysis_mode: str = "supportive"

    def to_dict(self) -> Dict[str, str]:
        return {"analysis_mode": self.analysis_mode}

    @staticmethod
    def from_dict(data: Dict[str, str]) -> "AppConfig":
        mode = str(data.get("analysis_mode", "supportive"))
        return AppConfig(analysis_mode=mode)


# Simple store with ID generation and JSON persistence.
class LogStore:
    def __init__(self, path: str = "training_log_data.json") -> None:
        self._path = Path(path)
        self._sessions: List[Session] = []
        self._reflections: List[Reflection] = []
        self._config = AppConfig()
        self._id_counter = itertools.count(1)
        self._load()

    def add_session(self, session: Session) -> None:
        self._sessions.append(session)
        self._save()

    def upsert_reflection(self, reflection: Reflection) -> None:
        # Keep at most one reflection per session for simple retrieval.
        for i, existing in enumerate(self._reflections):
            if existing.session_id == reflection.session_id:
                self._reflections[i] = reflection
                self._save()
                return
        self._reflections.append(reflection)
        self._save()

    def set_analysis_mode(self, mode: str) -> None:
        # Store as data so UI/CLI can change it later without code edits.
        self._config.analysis_mode = mode
        self._save()

    def next_id(self) -> int:
        return next(self._id_counter)

    @property
    def sessions(self) -> List[Session]:
        return list(self._sessions)

    @property
    def reflections(self) -> List[Reflection]:
        return list(self._reflections)

    @property
    def config(self) -> AppConfig:
        return self._config

    def get_reflection(self, session_id: int) -> Reflection | None:
        for reflection in self._reflections:
            if reflection.session_id == session_id:
                return reflection
        return None

    def _load(self) -> None:
        if not self._path.exists():
            return

        data = json.loads(self._path.read_text())
        self._config = AppConfig.from_dict(data.get("config", {}))
        self._sessions = [Session.from_dict(d) for d in data.get("sessions", [])]
        self._reflections = [Reflection.from_dict(d) for d in data.get("reflections", [])]

        max_id = max((s.id for s in self._sessions), default=0)
        self._id_counter = itertools.count(max_id + 1)

    def _save(self) -> None:
        payload = {
            "config": self._config.to_dict(),
            "sessions": [s.to_dict() for s in self._sessions],
            "reflections": [r.to_dict() for r in self._reflections],
        }
        self._path.write_text(json.dumps(payload, indent=2))


app = Flask(__name__)
store = LogStore()
reflection_engine = ReflectionEngine()
analysis_engine = AnalysisEngine()
exporter = Exporter()


SINGLE_TEMPLATE = """
<!doctype html>
<html lang="sv">
  <head>
    <title>Träningslogg</title>
    <style>
      :root {
        --bg: #f3f4f1;
        --card: #ffffff;
        --text: #1e1f1a;
        --muted: #5c5f55;
        --line: #e4e6df;
        --accent: #2f6f55;
        --shadow: 0 10px 30px rgba(20, 20, 20, 0.08);
        --radius: 16px;
      }
      :root[data-theme="dark"] {
        --bg: #111311;
        --card: #1b1e1b;
        --text: #f1f2ee;
        --muted: #b4b8ae;
        --line: #2a2e29;
        --accent: #7ac1a5;
        --shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "Georgia", "Times New Roman", serif;
        background: var(--bg);
        color: var(--text);
      }
      .page {
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
      }
      .card-wrap {
        position: relative;
        width: 100%;
        max-width: 700px;
      }
      .card {
        width: 100%;
        max-width: 700px;
        background: var(--card);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
        padding: 32px;
        border: 1px solid var(--line);
      }
      .flame {
        position: absolute;
        top: 24px;
        bottom: 24px;
        width: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 28px;
        opacity: 0.7;
        pointer-events: none;
      }
      .flame.left { left: -36px; }
      .flame.right { right: -36px; }
      @media (max-width: 760px) {
        .flame { display: none; }
      }
      h1 {
        margin: 0 0 8px 0;
        font-size: 28px;
        font-weight: 600;
      }
      .subtitle {
        margin: 0 0 24px 0;
        color: var(--muted);
        font-size: 16px;
      }
      h2 {
        margin: 24px 0 10px 0;
        font-size: 20px;
        font-weight: 600;
      }
      label {
        display: block;
        font-weight: 600;
        margin-bottom: 6px;
      }
      input[type="text"],
      input[type="number"] {
        width: 100%;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid var(--line);
        font-size: 16px;
        background: #fff;
        color: var(--text);
      }
      :root[data-theme="dark"] input[type="text"],
      :root[data-theme="dark"] input[type="number"] {
        background: #121412;
      }
      .field {
        margin-bottom: 18px;
      }
      .section {
        padding-top: 10px;
        border-top: 1px solid var(--line);
      }
      .actions {
        margin-top: 10px;
        display: flex;
        justify-content: flex-end;
      }
      button {
        background: var(--accent);
        color: #0d1b14;
        border: none;
        padding: 10px 16px;
        border-radius: 10px;
        font-size: 16px;
        cursor: pointer;
      }
      :root[data-theme="dark"] button {
        color: #0a1510;
      }
      button:focus {
        outline: 2px solid rgba(47, 111, 85, 0.3);
        outline-offset: 2px;
      }
      pre {
        white-space: pre-wrap;
        font-family: "Georgia", "Times New Roman", serif;
        background: #fafaf7;
        border: 1px solid var(--line);
        padding: 16px;
        border-radius: 12px;
        margin: 0 0 20px 0;
      }
      :root[data-theme="dark"] pre {
        background: #141714;
      }
      .links {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
      }
      a {
        color: var(--accent);
        text-decoration: none;
        font-weight: 600;
      }
      a:focus {
        outline: 2px solid rgba(47, 111, 85, 0.3);
        outline-offset: 2px;
      }
      .top-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 10px;
      }
      .theme-toggle {
        background: transparent;
        color: var(--text);
        border: 1px solid var(--line);
        padding: 8px 12px;
        border-radius: 10px;
        cursor: pointer;
        font-size: 14px;
      }
      :root[data-theme="dark"] .theme-toggle {
        color: var(--text);
      }
    </style>
  </head>
  <body>
    <div class="page">
      <div class="card-wrap">
        <div class="flame left">🔥</div>
        <div class="flame right">🔥</div>
        <div class="card">
          <div class="top-bar">
            <div>
              <h1>Träningslogg</h1>
              <p class="subtitle">Ett lugnt stöd för att följa dina pass och reflektioner.</p>
            </div>
            <button class="theme-toggle" type="button" id="theme-toggle">Växla tema</button>
          </div>

          <div class="section">
            <h2>Logga träningspass</h2>
            <form method="post">
              <div class="field">
                <label>Träningsform</label>
                <input type="text" name="activity_type" required>
              </div>
              <div class="field">
                <label>Tid (minuter)</label>
                <input type="number" name="duration_minutes" min="1" required>
              </div>
              <div class="field">
                <label>Upplevd ansträngning (1–10)</label>
                <input type="number" name="intensity" min="1" max="10" required>
              </div>
              <div class="actions">
                <button type="submit">Fortsätt</button>
              </div>
            </form>
          </div>

          {% if show_reflection %}
            <div class="section">
              <h2>Reflektion</h2>
              <p class="subtitle">Ta en minut och skriv ner dina tankar.</p>
              <form method="post" action="{{ url_for('reflection', session_id=session_id) }}">
                <input type="hidden" name="session_id" value="{{ session_id }}">
                {% for item in items %}
                  <div class="field">
                    <label>{{ loop.index }}. {{ item.question_text }}</label>
                    <input type="text" name="answer_{{ loop.index0 }}" value="{{ item.answer|e }}" required>
                  </div>
                {% endfor %}
                <div class="actions">
                  <button type="submit">Spara</button>
                </div>
              </form>
            </div>
          {% endif %}

          {% if show_analysis %}
            <div class="section">
              <h2>Analys</h2>
              <p class="subtitle">En kort sammanfattning av de senaste passen.</p>
              <pre>{{ analysis }}</pre>
            </div>
          {% endif %}

          <div class="links">
            <a href="{{ url_for('export_csv') }}">Exportera CSV</a>
          </div>
        </div>
      </div>
    </div>
    <script>
      (function () {
        const root = document.documentElement;
        const toggle = document.getElementById("theme-toggle");
        const saved = localStorage.getItem("tema");
        if (saved === "dark" || saved === "light") {
          root.setAttribute("data-theme", saved);
        }

        function currentTheme() {
          return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
        }

        function updateLabel() {
          toggle.textContent = currentTheme() === "dark" ? "Ljust läge" : "Mörkt läge";
        }

        toggle.addEventListener("click", function () {
          const next = currentTheme() === "dark" ? "light" : "dark";
          root.setAttribute("data-theme", next);
          localStorage.setItem("tema", next);
          updateLabel();
        });

        updateLabel();
      })();
    </script>
  </body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def log_session():
    if request.method == "POST":
        activity = request.form.get("activity_type", "").strip()
        duration_raw = request.form.get("duration_minutes", "0")
        intensity_raw = request.form.get("intensity", "0")

        duration = max(1, int(duration_raw))
        intensity = min(10, max(1, int(intensity_raw)))

        session = Session(
            id=store.next_id(),
            date=date.today(),
            activity_type=activity,
            duration_minutes=duration,
            intensity=intensity,
        )
        store.add_session(session)

        # Generate reflection immediately to keep the flow simple.
        reflection = reflection_engine.generate(session, trigger_type="system")
        store.upsert_reflection(reflection)

        return redirect(url_for("log_session", session_id=session.id, step="reflection"))

    session_id = request.args.get("session_id", type=int)
    step = request.args.get("step", "")
    show_reflection = step == "reflection" and session_id is not None
    show_analysis = step == "analysis"
    reflection_data = store.get_reflection(session_id) if show_reflection else None
    analysis_text = (
        analysis_engine.analyze(store.sessions, language_mode=store.config.analysis_mode)
        if show_analysis
        else ""
    )

    return render_template_string(
        SINGLE_TEMPLATE,
        show_reflection=show_reflection,
        show_analysis=show_analysis,
        session_id=session_id,
        items=reflection_data.items if reflection_data else [],
        analysis=analysis_text,
    )


@app.route("/reflection/<int:session_id>", methods=["GET", "POST"])
def reflection(session_id: int):
    reflection_data = store.get_reflection(session_id)
    if not reflection_data:
        # If a reflection is missing, regenerate to avoid a broken flow.
        session = next((s for s in store.sessions if s.id == session_id), None)
        if not session:
            return redirect(url_for("log_session"))
        reflection_data = reflection_engine.generate(session, trigger_type="system")
        store.upsert_reflection(reflection_data)

    if request.method == "POST":
        for i, item in enumerate(reflection_data.items):
            key = f"answer_{i}"
            item.answer = request.form.get(key, "").strip()
        store.upsert_reflection(reflection_data)
        return redirect(url_for("log_session", step="analysis"))

    return redirect(url_for("log_session", session_id=session_id, step="reflection"))


@app.route("/analysis")
def analysis():
    return redirect(url_for("log_session", step="analysis"))


@app.route("/export")
def export_csv():
    output_path = "training_log_export.csv"
    exporter.export_csv(store.sessions, store.reflections, output_path)
    return send_file(output_path, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
