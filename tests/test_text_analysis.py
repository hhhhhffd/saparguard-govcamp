import pytest

from app.processing.text.analyzer import analyze_message


@pytest.mark.parametrize(
    ("text", "message_type"),
    [
        ("🚖 БИШКЕК - АЛМАТЫ Toyota Avalon +77020007123", "driver_offer"),
        ("Ассалому алейкум Бишкек Алматы такси керек 5 адамга", "passenger_request"),
        ("с Алматы до Бишкека доставить посылку сколько будет?", "parcel_request"),
        ("Всем салют приобрету USDT TRC20 в большом количестве", "commercial_spam"),
        ("Дмитрий группага жазыш үчүн 10 адам кошуңуз", "service_message"),
        ("Алматыдан Бишкекке такси керек", "passenger_request"),
        ("Посылка аламын, Бишкек Алматы", "parcel_offer"),
        ("Күнү-түнү 24/7 аэропорт", "conversation"),
        ("привет", "conversation"),
        ("", "unknown"),
        ("Toyota Camry 50 Алматы Астана такси", "driver_offer"),
        ("Киа K7 бизнес класс", "conversation"),
        ("Хендай Грандер", "conversation"),
        ("Мерседес W220", "conversation"),
        ("Алмата → Ташкент выезд утром", "driver_offer"),
        ("Нур-Султан - Караганда такси", "driver_offer"),
        ("Ысык-Көлгө барам", "conversation"),
        ("Чолпон-Ата Бишкек такси керек", "passenger_request"),
        ("продам аккаунт telegram", "commercial_spam"),
        ("от двери до двери посылки", "parcel_offer"),
    ],
)
def test_classification_fixtures(text: str, message_type: str) -> None:
    assert analyze_message(text).classification.message_type == message_type


def test_required_driver_offer_extracts_structured_data() -> None:
    result = analyze_message("🚖 БИШКЕК - АЛМАТЫ Toyota Avalon +77020007123")
    assert {item.normalized_value for item in result.entities if item.entity_type == "phone"} == {
        "+77020007123"
    }
    assert result.routes[0].normalized_origin == "Бишкек"
    assert result.routes[0].normalized_destination == "Алматы"
    assert any(item.metadata.get("model") == "Avalon" for item in result.entities)


def test_phone_deduplication_and_non_phone_numbers() -> None:
    result = analyze_message("+7 702 000 71 23 wa.me/77020007123 цена 50 000 тенге 2022")
    phones = [item for item in result.entities if item.entity_type == "phone"]
    assert [item.normalized_value for item in phones] == ["+77020007123"]


def test_many_locations_do_not_create_cartesian_routes() -> None:
    result = analyze_message("Алматы Астана Тараз Шымкент Караганда")
    assert len([item for item in result.entities if item.entity_type == "location"]) == 5
    assert result.routes == ()


def test_analysis_is_reproducible() -> None:
    text = "Алматы → Бишкек Toyota Camry +996555401053"
    assert analyze_message(text) == analyze_message(text)
