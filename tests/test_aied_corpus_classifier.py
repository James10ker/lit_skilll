from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from classify_expand_aied_corpus import _direction_match_score, classify_record  # noqa: E402


class AiedCorpusClassifierTests(unittest.TestCase):
    def test_cancer_prediction_is_out_of_scope(self) -> None:
        result = classify_record(
            {
                "title": "Applications of Machine Learning in Cancer Prediction and Prognosis",
                "abstract": "This review examines machine learning models for cancer prognosis.",
            }
        )
        self.assertFalse(result["in_scope"])
        self.assertEqual(result["primary_topic_code"], "X00")

    def test_generic_aied_is_not_defaulted_to_generative_ai(self) -> None:
        result = classify_record(
            {
                "title": "Artificial Intelligence in Education: A Field Overview",
                "abstract": "This article surveys intelligent systems for teaching and learning.",
            }
        )
        self.assertTrue(result["in_scope"])
        self.assertEqual(result["primary_topic_code"], "O01")

    def test_bare_english_its_does_not_trigger_tutoring(self) -> None:
        result = classify_record(
            {
                "title": "A learning platform and its impact on students",
                "abstract": "The educational platform uses machine learning for course analytics.",
            }
        )
        self.assertNotIn(result["primary_topic_code"], {"T01", "T02", "T16"})

    def test_chatgpt_is_generative_ai(self) -> None:
        result = classify_record(
            {
                "title": "ChatGPT in Higher Education",
                "abstract": "This study examines a large language model used by university students.",
            }
        )
        self.assertTrue(result["in_scope"])
        self.assertEqual(result["primary_topic_code"], "E01")

    def test_special_education_direction_is_retained(self) -> None:
        result = classify_record(
            {
                "title": "An Intelligent Tutoring System for Autistic Learners",
                "abstract": "The tutor supports special education students in classroom learning.",
            }
        )
        self.assertTrue(result["in_scope"])
        self.assertEqual(result["primary_topic_code"], "T16")
        self.assertIn("F01", result["future_direction_codes"])

    def test_learning_approach_is_not_neural_teaching_evaluation(self) -> None:
        record = {
            "title": "Feedback seeking in higher education and a deep learning approach",
            "abstract": "Students describe their goal orientation and study habits.",
        }
        record["classification"] = classify_record(record)
        self.assertLess(_direction_match_score(record, "F06"), 0)

    def test_generic_emotion_tutorial_is_not_affective_education(self) -> None:
        record = {
            "title": "EEG Based Emotion Recognition: A Tutorial and Review",
            "abstract": "Educational applications are mentioned among many domains.",
        }
        record["classification"] = classify_record(record)
        self.assertLess(_direction_match_score(record, "F07"), 0)


if __name__ == "__main__":
    unittest.main()
