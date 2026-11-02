import pytest

from rag.flow.document_metadata.metadata import attach_document_metadata, extract_document_metadata


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "徐工铲运XC938U装载机控制系统使用说明书（工程师版）.docx",
            {
                "brand": ["徐工"],
                "equipment_type": ["轮胎式装载机"],
                "models": ["XC938U"],
                "manual_type": ["操作方法"],
            },
        ),
        (
            "操保手册(中文)-253910058-975(EU)EV.AX01宁德+微特利+湿桥+电液比例+空调+小高卸+20260405田建华.docx",
            {"manual_type": ["操作方法", "保养步骤"]},
        ),
        (
            "XC975-EV（253913260、253913261）中文操作与保养手册刘浩202608.docx",
            {
                "models": ["XC975-EV"],
                "manual_type": ["操作方法", "保养步骤"],
            },
        ),
        (
            "XCMG-XC975EV轮胎式装载机维修保养手册.docx",
            {
                "brand": ["徐工"],
                "equipment_type": ["轮胎式装载机"],
                "models": ["XC975EV"],
                "manual_type": ["保养步骤", "故障排查"],
            },
        ),
        (
            "XE135D_XE155D_XE155DK液压挖掘机操作与保养手册_PS00001164.docx",
            {
                "equipment_type": ["液压挖掘机"],
                "models": ["XE135D", "XE155D", "XE155DK"],
                "manual_code": ["PS00001164"],
                "manual_type": ["操作方法", "保养步骤"],
            },
        ),
        (
            "LW500HV-GIV轮胎式装载机操作与保养手册_PS00011702.docx",
            {
                "equipment_type": ["轮胎式装载机"],
                "models": ["LW500HV-GIV"],
                "manual_code": ["PS00011702"],
                "manual_type": ["操作方法", "保养步骤"],
            },
        ),
    ],
)
def test_extracts_only_approved_metadata_fields(filename, expected):
    assert extract_document_metadata(filename) == expected


def test_omits_every_field_when_filename_has_no_reliable_evidence():
    assert extract_document_metadata("253913261刘浩20260824.docx") == {}


def test_does_not_expand_model_aliases_or_related_models():
    metadata = extract_document_metadata("XC975-EV维修手册.docx")

    assert metadata == {
        "models": ["XC975-EV"],
        "manual_type": ["故障排查"],
    }


def test_does_not_misclassify_internal_codes_as_models():
    metadata = extract_document_metadata("253913261宁德423kWh+WP10HG230E476+CT1维修手册.docx")

    assert metadata == {"manual_type": ["故障排查"]}


def test_all_extracted_values_are_string_arrays():
    metadata = extract_document_metadata(
        "徐工LW500HV-GIV轮胎式装载机操作与保养手册_PS00011702.docx"
    )

    assert metadata
    assert all(isinstance(value, list) and value for value in metadata.values())
    assert all(isinstance(item, str) for value in metadata.values() for item in value)


def test_attaches_metadata_only_to_first_chunk_without_mutating_input():
    chunks = [{"text": "first"}, {"text": "second"}]

    output = attach_document_metadata(chunks, "徐工XC938U装载机操作手册.docx")

    assert output[0]["metadata"] == {
        "brand": ["徐工"],
        "equipment_type": ["轮胎式装载机"],
        "models": ["XC938U"],
        "manual_type": ["操作方法"],
    }
    assert "metadata" not in output[1]
    assert all("metadata" not in chunk for chunk in chunks)


def test_merges_filename_metadata_with_existing_string_arrays():
    chunks = [
        {
            "text": "first",
            "metadata": {
                "models": ["XE155D", "XE155DK"],
                "systems": ["发动机"],
            },
        }
    ]

    output = attach_document_metadata(chunks, "XE155D液压挖掘机操作手册.docx")

    assert output[0]["metadata"] == {
        "models": ["XE155D", "XE155DK"],
        "systems": ["发动机"],
        "equipment_type": ["液压挖掘机"],
        "manual_type": ["操作方法"],
    }
    assert chunks[0]["metadata"]["models"] == ["XE155D", "XE155DK"]
