"""Инструменты этапа 2. Импорт не выполняет сетевых запросов."""


def create_tools():
    """Создать инструменты без запросов; ключ поиска проверяется при вызове."""
    from .calculator import TripCostCalculatorTool
    from .web import WebsiteReaderTool
    from .search import InternetSearchTool

    return {
        "search": InternetSearchTool(),
        "reader": WebsiteReaderTool(max_text_chars=6000),
        "calculator": TripCostCalculatorTool(),
    }
