from unittest.mock import MagicMock, patch

from ats.greenhouse_schema import (
    GreenhouseFormField,
    fetch_job_schema,
    map_plan_to_schema,
    missing_required_fields,
)

REAL_QUESTIONS_PAYLOAD = [
    {
        "description": None,
        "label": "First Name",
        "required": True,
        "fields": [{"name": "first_name", "type": "input_text", "values": []}],
    },
    {
        "description": None,
        "label": "Last Name",
        "required": True,
        "fields": [{"name": "last_name", "type": "input_text", "values": []}],
    },
    {
        "description": None,
        "label": "Email",
        "required": True,
        "fields": [{"name": "email", "type": "input_text", "values": []}],
    },
    {
        "description": None,
        "label": "Phone",
        "required": True,
        "fields": [{"name": "phone", "type": "input_text", "values": []}],
    },
    {
        "description": None,
        "label": "Resume/CV",
        "required": False,
        "fields": [
            {"name": "resume", "type": "input_file", "values": []},
            {"name": "resume_text", "type": "textarea", "values": []},
        ],
    },
    {
        "description": None,
        "label": "Cover Letter",
        "required": False,
        "fields": [
            {"name": "cover_letter", "type": "input_file", "values": []},
            {"name": "cover_letter_text", "type": "textarea", "values": []},
        ],
    },
    {
        "description": None,
        "label": "Why do you want to work at Discord?",
        "required": True,
        "fields": [
            {"name": "question_39255646002", "type": "textarea", "values": []}
        ],
    },
    {
        "description": None,
        "label": "LinkedIn Profile",
        "required": False,
        "fields": [
            {"name": "question_39255647002", "type": "input_text", "values": []}
        ],
    },
    {
        "description": None,
        "label": "Website",
        "required": False,
        "fields": [
            {"name": "question_39255648002", "type": "input_text", "values": []}
        ],
    },
    {
        "description": None,
        "label": "How did you hear about this job?",
        "required": False,
        "fields": [
            {"name": "question_39255649002", "type": "input_text", "values": []}
        ],
    },
    {
        "description": None,
        "label": "Are you legally authorized to work in the United States for our Company?",
        "required": True,
        "fields": [
            {
                "name": "question_39255650002",
                "type": "multi_value_single_select",
                "values": [
                    {"label": "Yes", "value": 1},
                    {"label": "No", "value": 0},
                ],
            }
        ],
    },
    {
        "description": None,
        "label": "Are you currently located in the US?",
        "required": True,
        "fields": [
            {
                "name": "question_39255651002",
                "type": "multi_value_single_select",
                "values": [
                    {"label": "Yes", "value": 1},
                    {"label": "No", "value": 0},
                ],
            }
        ],
    },
    {
        "description": None,
        "label": "Are you currently based in or willing to relocate to LA or NY for this position? ",
        "required": True,
        "fields": [
            {
                "name": "question_39255652002",
                "type": "multi_value_single_select",
                "values": [
                    {"label": "Yes", "value": 1},
                    {"label": "No", "value": 0},
                ],
            }
        ],
    },
]

DEMOGRAPHIC_QUESTIONS_PAYLOAD = {
    "questions": [
        {
            "id": 1,
            "label": "Gender",
            "required": True,
            "answer_options": [{"id": 10, "label": "Decline to state"}],
        }
    ]
}

FULL_API_RESPONSE = {
    "questions": REAL_QUESTIONS_PAYLOAD,
    "demographic_questions": DEMOGRAPHIC_QUESTIONS_PAYLOAD,
}


def _mock_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_fetch_job_schema_flattens_multi_field_question():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)

    schema = fetch_job_schema("discord", "8945798002", http_client=mock_client)

    resume_fields = [f for f in schema if f.label == "Resume/CV"]
    assert len(resume_fields) == 2

    resume_file = next(f for f in resume_fields if f.field_id == "resume")
    assert resume_file.field_type == "input_file"
    assert resume_file.required is False
    assert resume_file.is_standard is True
    assert resume_file.options == []

    resume_text = next(f for f in resume_fields if f.field_id == "resume_text")
    assert resume_text.field_type == "textarea"
    assert resume_text.required is False
    assert resume_text.is_standard is True
    assert resume_text.options == []


def test_fetch_job_schema_custom_single_field():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)

    schema = fetch_job_schema("discord", "8945798002", http_client=mock_client)

    why_discord = [
        f for f in schema if f.label == "Why do you want to work at Discord?"
    ]
    assert len(why_discord) == 1
    field = why_discord[0]
    assert field.field_id == "question_39255646002"
    assert field.field_type == "textarea"
    assert field.required is True
    assert field.is_standard is False
    assert field.options == []


def test_fetch_job_schema_select_options():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)

    schema = fetch_job_schema("discord", "8945798002", http_client=mock_client)

    auth_field = next(
        f
        for f in schema
        if f.label
        == "Are you legally authorized to work in the United States for our Company?"
    )
    assert auth_field.field_id == "question_39255650002"
    assert auth_field.field_type == "multi_value_single_select"
    assert auth_field.required is True
    assert auth_field.options == ["Yes", "No"]


def test_fetch_job_schema_ignores_demographic_questions():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)

    schema = fetch_job_schema("discord", "8945798002", http_client=mock_client)

    assert not any("gender" in f.label.casefold() for f in schema)
    assert not any("demographic" in f.field_id.casefold() for f in schema)
    assert not any(f.field_id == "1" for f in schema)


def test_fetch_job_schema_default_client():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)

    with patch("ats.greenhouse_schema.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value = mock_client
        schema = fetch_job_schema("discord", "8945798002")

    mock_client.get.assert_called_once_with(
        "https://boards-api.greenhouse.io/v1/boards/discord/jobs/8945798002?questions=true"
    )
    assert len(schema) == 15


def test_map_plan_to_schema_matching_and_unmatched():
    schema = [
        GreenhouseFormField(
            field_id="first_name",
            label="First Name",
            field_type="input_text",
            required=True,
            is_standard=True,
        ),
        GreenhouseFormField(
            field_id="question_39255646002",
            label="Why do you want to work at Discord?",
            field_type="textarea",
            required=True,
            is_standard=False,
        ),
        GreenhouseFormField(
            field_id="question_39255647002",
            label="LinkedIn Profile",
            field_type="input_text",
            required=False,
            is_standard=False,
        ),
        GreenhouseFormField(
            field_id="phone",
            label="Phone",
            field_type="input_text",
            required=True,
            is_standard=True,
        ),
    ]

    plan_fields = [
        {"field_name": "first_name", "value": "Ada"},
        {
            "field_name": "why do you want to work at discord?",
            "value": "I love the product and platform.",
        },
        {"field_name": "unknown_field", "value": "ignored"},
    ]

    results = map_plan_to_schema(plan_fields, schema)

    assert len(results) == 4

    first_name_res = next(r for r in results if r.field_id == "first_name")
    assert first_name_res.mapped_value == "Ada"
    assert first_name_res.plan_field_name == "first_name"
    assert first_name_res.required is True

    why_res = next(r for r in results if r.field_id == "question_39255646002")
    assert why_res.mapped_value == "I love the product and platform."
    assert why_res.plan_field_name == "why do you want to work at discord?"
    assert why_res.required is True

    linkedin_res = next(r for r in results if r.field_id == "question_39255647002")
    assert linkedin_res.mapped_value is None
    assert linkedin_res.plan_field_name is None
    assert linkedin_res.required is False

    phone_res = next(r for r in results if r.field_id == "phone")
    assert phone_res.mapped_value is None
    assert phone_res.plan_field_name is None
    assert phone_res.required is True


def test_missing_required_fields():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(FULL_API_RESPONSE)
    schema = fetch_job_schema("discord", "8945798002", http_client=mock_client)

    plan_fields = [
        {"field_name": "first_name", "value": "Jane"},
        {"field_name": "last_name", "value": "Doe"},
        {"field_name": "email", "value": "jane@example.com"},
        # phone missing (required=True)
        # Why do you want to work at Discord? (required=True) mapped:
        {
            "field_name": "Why do you want to work at Discord?",
            "value": "Great mission.",
        },
        # question_39255650002 (US auth, required=True) mapped by exact id:
        {"field_name": "question_39255650002", "value": "Yes"},
        # question_39255651002 (currently located in US, required=True) missing
        # question_39255652002 (relocate to LA/NY, required=True) missing
    ]

    mapping = map_plan_to_schema(plan_fields, schema)
    missing = missing_required_fields(mapping)

    assert missing == ["phone", "question_39255651002", "question_39255652002"]
