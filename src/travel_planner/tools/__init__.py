"""Инструменты этапа 2. Импорт не выполняет сетевых запросов."""


def create_tools():
    """Создать инструменты без запросов; ключ поиска проверяется при вызове."""
    from .calculator import TripCostCalculatorTool
    from .web import WebsiteReaderTool
    from .search import InternetSearchTool

    return {
        "search": InternetSearchTool(),
        "reader": WebsiteReaderTool(),
        "calculator": TripCostCalculatorTool(),
    }
