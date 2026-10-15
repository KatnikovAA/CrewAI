"""ScrapeWebsiteTool с явными статусами и проверкой HTTP-ответа."""

from bs4 import BeautifulSoup
from crewai_tools import ScrapeWebsiteTool
from crewai_tools.security.safe_requests import safe_get_bounded
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
import requests


class WebsiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    website_url: HttpUrl = Field(description="URL публичной HTML или текстовой страницы (http/https)")


class WebsiteReaderTool(ScrapeWebsiteTool):
    name: str = "website_reader"
    description: str = (
        "Читает текст публичной HTML/текстовой страницы по website_url. "
        "Возвращает источник и status ok/empty/error. JavaScript не исполняется."
    )
    args_schema: type[BaseModel] = WebsiteInput

    def _run(self, website_url) -> dict:
        url = str(WebsiteInput.model_validate({"website_url": website_url}).website_url)
        base = {"requested_url": url, "source_url": url, "text": ""}
        try:
            body, content_type, final_url = safe_get_bounded(
                url, max_bytes=2_000_000, timeout=15, headers=self.headers,
            )
            base["source_url"] = final_url
            mime = content_type.split(";", 1)[0].strip().lower()
            if mime not in {"text/html", "application/xhtml+xml", "text/plain"}:
                return {**base, "status": "error", "error_code": "unsupported_content",
                        "message": "Поддерживаются только HTML и text/plain."}
            if mime == "text/plain":
                # BeautifulSoup использует объявленную кодировку или определяет её.
                from bs4 import UnicodeDammit
                text = (UnicodeDammit(body).unicode_markup or "").strip()
            else:
                page = BeautifulSoup(body, "html.parser")
                for element in page(["script", "style", "noscript", "template"]):
                    element.decompose()
                text = " ".join(page.get_text(" ", strip=True).split())
            return {**base, "status": "ok" if text else "empty", "text": text,
                    "error_code": None, "message": "" if text else "На странице нет доступного текста."}
        except requests.HTTPError as error:
            code = error.response.status_code if error.response is not None else "error"
            return {**base, "status": "error", "error_code": f"http_{code}", "message": "Сайт вернул HTTP-ошибку."}
        except requests.RequestException:
            return {**base, "status": "error", "error_code": "network_error", "message": "Не удалось получить страницу: проверьте доступ и URL."}
        except ValueError:
            return {**base, "status": "error", "error_code": "page_rejected", "message": "URL, перенаправление или размер страницы отклонены."}
