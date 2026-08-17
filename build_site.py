#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — пересобирает вкладки цен (и SEO-разметку) в
miolaser-landing.html на основе данных из prices.txt.

Как запустить:
    Дважды кликните rebuild_site.bat (Windows) или rebuild_site.command (Mac).
    Либо в терминале:  python3 build_site.py

Файлы prices.txt, build_site.py и miolaser-landing.html должны лежать
в одной папке.

Скрипт безопасно перезапускать сколько угодно раз: он трогает только
блок между <!-- PRICES:AUTO-START --> и <!-- PRICES:AUTO-END --> внутри
HTML, плюс список услуг в SEO-разметке (JSON-LD). Всё остальное на
сайте не меняется. Перед каждым запуском сохраняется резервная копия
сайта (см. папку backups).
"""
import re
import sys
import json
import html
import shutil
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PRICES_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR / "prices.txt"
HTML_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else SCRIPT_DIR / "miolaser-landing.html"

START_MARKER = "<!-- PRICES:AUTO-START (генерируется из prices.txt — не редактируйте вручную, правки перезапишутся) -->"
END_MARKER = "<!-- PRICES:AUTO-END -->"

GEO_START = "<!-- GEO:AUTO-START (генерируется из prices.txt, раздел НАСТРОЙКИ — не редактируйте вручную) -->"
GEO_END = "<!-- GEO:AUTO-END -->"

METRIKA_START = "<!-- YANDEX METRIKA:AUTO-START (счётчик и ID — редактируются в prices.txt, раздел НАСТРОЙКИ) -->"
METRIKA_END = "<!-- YANDEX METRIKA:AUTO-END -->"

SITE_URL_START = "<!-- SITE-URL:AUTO-START (генерируется из prices.txt, раздел НАСТРОЙКИ, ключ SITE_URL — не редактируйте вручную) -->"
SITE_URL_END = "<!-- SITE-URL:AUTO-END -->"

GOALS_START = "<!-- GOALS:AUTO-START (цели Яндекс.Метрики — редактируются в prices.txt, раздел НАСТРОЙКИ, ключи GOAL_...) -->"
GOALS_END = "<!-- GOALS:AUTO-END -->"

ROUTE_HERO_START = "<!-- ROUTE-HERO:AUTO-START (генерируется из prices.txt GEO_LAT/GEO_LON — не редактируйте вручную) -->"
ROUTE_HERO_END = "<!-- ROUTE-HERO:AUTO-END -->"

ROUTE_CONTACTS_START = "<!-- ROUTE-CONTACTS:AUTO-START (генерируется из prices.txt GEO_LAT/GEO_LON — не редактируйте вручную) -->"
ROUTE_CONTACTS_END = "<!-- ROUTE-CONTACTS:AUTO-END -->"

VERIFY_START = "<!-- YANDEX VERIFICATION:AUTO-START (код подтверждения — редактируется в prices.txt, раздел НАСТРОЙКИ, ключ YANDEX_VERIFICATION) -->"
VERIFY_END = "<!-- YANDEX VERIFICATION:AUTO-END -->"

# Ключ настройки -> (имя-по-умолчанию, человеческое описание для предупреждений)
GOAL_KEYS = {
    "GOAL_TELEGRAM": "click_telegram",
    "GOAL_YCLIENTS": "click_yclients",
    "GOAL_MAPS_YANDEX": "click_maps_yandex",
    "GOAL_MAPS_2GIS": "click_maps_2gis",
    "GOAL_VK": "click_vk",
    "GOAL_PHONE": "click_phone",
    "GOAL_QUIZ": "click_quiz",
}

VALID_ON = {"ВКЛ"}
VALID_OFF = {"ВЫКЛ"}


def read_text_robust(path):
    """Читает текстовый файл, даже если он сохранён не в UTF-8
    (частая ситуация со старым Блокнотом на Windows)."""
    for enc in ("utf-8-sig", "cp1251", "cp1252"):
        try:
            return path.read_text(encoding=enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RuntimeError(
        f'Не смог прочитать "{path.name}" ни в одной из известных кодировок '
        f"(UTF-8, Windows-1251, Windows-1252). Пересохраните файл как UTF-8 "
        f"через меню редактора (в Блокноте: Файл → Сохранить как → кодировка UTF-8)."
    )


def parse_prices(path):
    text, enc = read_text_robust(path)
    categories = []
    settings = {}
    current_cat = None
    current_group = None
    in_settings = False
    warnings = []
    seen_tab_ids = set()

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            body = stripped[3:]
            parts = [p.strip() for p in body.split("|")]
            label = parts[0]
            is_settings = any(p.lower().replace(" ", "") == "type=settings" for p in parts[1:])
            if is_settings:
                in_settings = True
                current_cat = None
                current_group = None
                continue
            in_settings = False
            tab_id = None
            tab_title = label
            for p in parts[1:]:
                if p.lower().startswith("tab="):
                    tab_id = p.split("=", 1)[1].strip()
                elif "заголовок вкладки" in p.lower():
                    tab_title = p.split(":", 1)[1].strip()
            tab_id = tab_id or re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"cat{len(categories)+1}"
            if tab_id in seen_tab_ids:
                warnings.append(
                    f'Строка {line_no}: у категории "{label}" повторяется tab="{tab_id}" — '
                    f"уже использован другой категорией. Переименуйте один из них, иначе вкладки могут работать неправильно."
                )
            seen_tab_ids.add(tab_id)
            current_cat = {"id": tab_id, "title": tab_title, "groups": []}
            categories.append(current_cat)
            current_group = None
            continue
        if in_settings:
            if stripped.startswith("#"):
                continue  # комментарий — пропускаем
            if ":" not in stripped:
                warnings.append(
                    f'Строка {line_no}: в разделе НАСТРОЙКИ не нашёл двоеточие "Ключ: значение" — '
                    f"пропустил эту строку: {stripped[:60]}"
                )
                continue
            key, _, value = stripped.partition(":")
            settings[key.strip().upper()] = value.strip()
            continue
        if stripped.startswith("### "):
            if current_cat is None:
                warnings.append(
                    f'Строка {line_no}: заголовок подраздела "{stripped[4:].strip()}" встретился '
                    f'до того, как появилась категория (## ...) — пропустил эту строку.'
                )
                continue
            current_group = {"name": stripped[4:].strip(), "items": []}
            current_cat["groups"].append(current_group)
            continue
        if stripped.startswith("#"):
            continue  # комментарий — пропускаем
        if "|" not in stripped:
            continue
        if current_cat is None:
            warnings.append(
                f"Строка {line_no}: услуга встретилась до того, как появилась категория "
                f"(## ...) — пропустил эту строку: {stripped[:60]}"
            )
            continue

        # ВКЛ | Название | Цена | Длительность | Примечание
        # maxsplit=4: всё, что после 4-го "|" (включая случайные лишние "|"),
        # целиком уходит в примечание — так пользователь не потеряет текст,
        # если случайно наберёт лишний разделитель.
        cols = [c.strip() for c in stripped.split("|", 4)]
        while len(cols) < 5:
            cols.append("")
        enabled_raw, name, price, duration, note = cols[:5]

        if not name:
            warnings.append(f"Строка {line_no}: у услуги не указано название — пропустил эту строку.")
            continue

        enabled_norm = enabled_raw.upper().strip()
        if enabled_norm in VALID_ON:
            enabled = True
        elif enabled_norm in VALID_OFF:
            enabled = False
        else:
            enabled = False
            warnings.append(
                f'Строка {line_no}: не понял значение "{enabled_raw}" (ожидал ВКЛ или ВЫКЛ) '
                f'— услуга "{name}" временно скрыта с сайта. Проверьте написание.'
            )

        if price not in ("", "0"):
            try:
                int(price)
            except ValueError:
                warnings.append(
                    f'Строка {line_no}: цена "{price}" у услуги "{name}" — не похоже на число. '
                    f"Пишите только цифры, без пробелов и без ₽ (например: 1200)."
                )

        if current_group is None:
            current_group = {"name": None, "items": []}
            current_cat["groups"].append(current_group)
        current_group["items"].append(
            {"enabled": enabled, "name": name, "price": price, "duration": duration, "note": note}
        )

    if not categories:
        raise RuntimeError(
            f'В файле "{path.name}" не нашёл ни одной категории услуг (строки, начинающиеся с "## "). '
            f"Проверьте, что файл не был случайно повреждён при сохранении."
        )

    if settings:
        for req in ("GEO_LAT", "GEO_LON"):
            val = settings.get(req, "")
            if val:
                try:
                    float(val)
                except ValueError:
                    warnings.append(
                        f'В разделе НАСТРОЙКИ значение {req}="{val}" не похоже на число '
                        f"— гео-метки могут не сработать. Проверьте, что там координата вида 60.015125."
                    )
        has_lat = bool(settings.get("GEO_LAT", "").strip())
        has_lon = bool(settings.get("GEO_LON", "").strip())
        if has_lat != has_lon:
            missing = "GEO_LON" if has_lat else "GEO_LAT"
            warnings.append(
                f"В разделе НАСТРОЙКИ указана только одна координата (не хватает {missing}) — "
                f"гео-метки geo.position/ICBM не будут добавлены на сайт, пока не заполнены обе "
                f"координаты GEO_LAT и GEO_LON."
            )

        metrika_id_raw = settings.get("YANDEX_METRIKA_ID", "").strip()
        if metrika_id_raw in ("", "00000000"):
            warnings.append(
                "В разделе НАСТРОЙКИ пока не указан настоящий номер счётчика Яндекс.Метрики "
                "(YANDEX_METRIKA_ID = 00000000, это заглушка) — статистика посещений и переходов "
                "по геометкам собираться не будет, пока вы не впишете туда реальный номер счётчика "
                "с metrika.yandex.ru (см. подсказку прямо в prices.txt)."
            )
        elif not metrika_id_raw.isdigit():
            digits_only = re.sub(r"[^0-9]", "", metrika_id_raw)
            warnings.append(
                f'В разделе НАСТРОЙКИ значение YANDEX_METRIKA_ID="{metrika_id_raw}" содержит нецифровые '
                f'символы — счётчик Яндекс.Метрики ожидает только цифры (например: 12345678). '
                + (
                    f'На сайт попадёт только цифровая часть: "{digits_only}" — проверьте, что это верный номер счётчика.'
                    if digits_only
                    else 'Цифр там не нашлось вообще, поэтому на сайте останется заглушка 00000000 — счётчик работать не будет.'
                )
            )

        goal_names_seen = {}
        for goal_key, default_name in GOAL_KEYS.items():
            raw = settings.get(goal_key, "").strip()
            name = raw or default_name
            if raw and " " in raw:
                warnings.append(
                    f'В разделе НАСТРОЙКИ значение {goal_key}="{raw}" содержит пробелы — для имени цели '
                    f"лучше использовать латиницу/цифры/подчёркивания без пробелов, иначе в Метрике "
                    f"такую цель может быть неудобно искать и вводить."
                )
            if name in goal_names_seen:
                warnings.append(
                    f'В разделе НАСТРОЙКИ ключи {goal_names_seen[name]} и {goal_key} используют одинаковое '
                    f'имя цели "{name}" — переходы по разным ссылкам будут смешиваться в один отчёт '
                    f"в Метрике. Задайте разные имена, если хотите считать их по отдельности."
                )
            else:
                goal_names_seen[name] = goal_key

    return categories, settings, warnings, enc


def fmt_price(price_str):
    try:
        n = int(price_str)
    except ValueError:
        return html.escape(price_str)
    return f"{n:,}".replace(",", " ") + " ₽"


def build_price_cell(item):
    price_txt = fmt_price(item["price"]) if item["price"] not in ("", "0") else "уточняйте при записи"
    if item["note"]:
        price_txt = f'{price_txt} <span class="price-sub">· {html.escape(item["note"])}</span>'
    return price_txt


def render_panel(cat, is_first):
    parts = [f'      <div class="price-panel{" active" if is_first else ""}" id="tab-{html.escape(cat["id"])}">']
    any_group_named = any(g["name"] for g in cat["groups"])
    for group in cat["groups"]:
        items = [it for it in group["items"] if it["enabled"]]
        if not items:
            continue
        if group["name"] and any_group_named:
            parts.append(f'        <div class="price-group">{html.escape(group["name"])}</div>')
        parts.append('        <table class="price-table">')
        for it in items:
            price_cell = build_price_cell(it)
            safe_name = html.escape(it["name"])
            safe_dur = html.escape(it["duration"]) if it["duration"] and it["duration"] != "—" else ""
            dur = f' <span class="price-dur">{safe_dur}</span>' if safe_dur else ""
            parts.append(f"          <tr><td>{safe_name}{dur}</td><td>{price_cell}</td></tr>")
        parts.append("        </table>")
    parts.append("      </div>")
    return "\n".join(parts)


def render_tabs_and_panels(categories):
    buttons = ['      <div class="price-tabs" role="tablist">']
    for i, cat in enumerate(categories):
        active = " active" if i == 0 else ""
        buttons.append(
            f'        <button class="tab-btn{active}" data-tab="{html.escape(cat["id"])}">{html.escape(cat["title"])}</button>'
        )
    buttons.append("      </div>")
    panels = [render_panel(cat, i == 0) for i, cat in enumerate(categories)]
    return "\n".join(buttons) + "\n\n" + "\n".join(panels)


def render_offer_catalog(categories):
    offers = []
    for cat in categories:
        for group in cat["groups"]:
            for it in group["items"]:
                if not it["enabled"] or it["price"] in ("", "0"):
                    continue
                try:
                    price_val = int(it["price"])
                except ValueError:
                    continue
                offers.append(
                    {
                        "@type": "Offer",
                        "itemOffered": {"@type": "Service", "name": it["name"], "category": cat["title"]},
                        "price": price_val,
                        "priceCurrency": "RUB",
                    }
                )
    return offers


def update_json_ld(html_text, offers, settings=None):
    """Обновляет hasOfferCatalog.itemListElement (и, если заданы настройки
    из раздела НАСТРОЙКИ, гео-координаты/адрес/ссылки) полноценным разбором
    JSON, а не текстовым совпадением (regex) — не зависит от того, какие
    символы оказались внутри названий услуг."""
    pattern = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

    updated = False
    new_pos = 0
    result = []
    for m in pattern.finditer(html_text):
        result.append(html_text[new_pos:m.start(1)])
        block_text = m.group(1)
        try:
            data = json.loads(block_text)
        except json.JSONDecodeError:
            result.append(block_text)
            new_pos = m.end(1)
            continue

        if isinstance(data, dict) and "hasOfferCatalog" in data:
            data["hasOfferCatalog"]["itemListElement"] = offers

            if settings:
                address = data.get("address")
                if isinstance(address, dict):
                    if settings.get("ADDRESS"):
                        address["streetAddress"] = settings["ADDRESS"]
                    if settings.get("CITY"):
                        address["addressLocality"] = settings["CITY"]
                    if settings.get("DISTRICT"):
                        address["addressRegion"] = settings["DISTRICT"]
                    if settings.get("POSTAL_CODE"):
                        address["postalCode"] = settings["POSTAL_CODE"]

                lat_raw, lon_raw = settings.get("GEO_LAT"), settings.get("GEO_LON")
                if lat_raw and lon_raw:
                    try:
                        geo = data.get("geo") if isinstance(data.get("geo"), dict) else {}
                        geo["@type"] = "GeoCoordinates"
                        geo["latitude"] = float(lat_raw)
                        geo["longitude"] = float(lon_raw)
                        data["geo"] = geo
                    except ValueError:
                        pass

                if settings.get("YANDEX_MAPS_URL"):
                    data["hasMap"] = settings["YANDEX_MAPS_URL"]
                if settings.get("SITE_URL"):
                    site_url = settings["SITE_URL"].rstrip("/") + "/"
                    data["url"] = site_url
                    # data["image"] в исходном шаблоне — это <домен>/images/og-cover.jpg;
                    # если поменяли домен, картинка должна ссылаться на новый (сохраняя
                    # путь images/... — берём всё, что шло после домена в старом значении).
                    if isinstance(data.get("image"), str) and "://" in data["image"]:
                        old_path = data["image"].split("://", 1)[1].split("/", 1)
                        og_path = old_path[1] if len(old_path) > 1 else "images/og-cover.jpg"
                        data["image"] = site_url + og_path

            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            # Защита от "выхода" из <script>: если в название услуги, адрес или
            # любое другое значение случайно попадёт текст "</script", браузер
            # закроет тег скрипта прямо посреди JSON — весь остаток случайного
            # текста после него станет исполняемым HTML/JS. Экранируем "</",
            # это стандартная практика для JSON, вставляемого в <script>.
            json_str = json_str.replace("</", "<\\/")
            result.append("\n" + json_str + "\n")
            updated = True
        else:
            result.append(block_text)
        new_pos = m.end(1)
    result.append(html_text[new_pos:])
    return "".join(result), updated


def render_geo_block(settings):
    region = settings.get("GEO_REGION", "").strip()
    city = settings.get("CITY", "").strip()
    address = settings.get("ADDRESS", "").strip()
    placename = ", ".join(p for p in (city, address) if p)
    lat = settings.get("GEO_LAT", "").strip()
    lon = settings.get("GEO_LON", "").strip()

    lines = [GEO_START]
    if region:
        lines.append(f'<meta name="geo.region" content="{html.escape(region)}">')
    if placename:
        lines.append(f'<meta name="geo.placename" content="{html.escape(placename)}">')
    if lat and lon:
        lines.append(f'<meta name="geo.position" content="{html.escape(lat)};{html.escape(lon)}">')
        lines.append(f'<meta name="ICBM" content="{html.escape(lat)}, {html.escape(lon)}">')
    lines.append(GEO_END)
    return "\n".join(lines)


def apply_geo_block(html_text, settings):
    start_idx = html_text.find(GEO_START)
    end_idx = html_text.find(GEO_END)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    new_html = html_text[:start_idx] + render_geo_block(settings) + html_text[end_idx + len(GEO_END):]
    return new_html, True


def render_verification_block(settings):
    code = settings.get("YANDEX_VERIFICATION", "").strip()
    lines = [VERIFY_START]
    if code:
        lines.append(f'<meta name="yandex-verification" content="{html.escape(code)}">')
    else:
        lines.append(
            "<!-- Код подтверждения прав на сайт в Яндекс.Вебмастере пока не указан "
            "(YANDEX_VERIFICATION в prices.txt пуст) — тег не выводится, это нормально. -->"
        )
    lines.append(VERIFY_END)
    return "\n".join(lines)


def apply_verification_block(html_text, settings):
    start_idx = html_text.find(VERIFY_START)
    end_idx = html_text.find(VERIFY_END)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    new_html = html_text[:start_idx] + render_verification_block(settings) + html_text[end_idx + len(VERIFY_END):]
    return new_html, True


def render_metrika_block(settings):
    digits = re.sub(r"[^0-9]", "", settings.get("YANDEX_METRIKA_ID", ""))
    counter_id = digits if digits else "00000000"
    lines = [
        METRIKA_START,
        "<!-- ВАЖНО: ниже плейсхолдер. Замените YANDEX_METRIKA_ID в prices.txt на реальный номер счётчика",
        "     с metrika.yandex.ru — без него посещения и переходы с геометок Яндекс.Бизнеса не будут",
        "     фиксироваться нигде. Регистрация счётчика бесплатна. -->",
        '<script type="text/javascript">',
        "   (function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};",
        "   m[i].l=1*new Date();",
        "   for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}",
        "   k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})",
        '   (window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");',
        "",
        f'   ym({counter_id}, "init", {{ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", accurateTrackBounce:true, trackLinks:true}});',
        "</script>",
        f'<noscript><div><img src="https://mc.yandex.ru/watch/{counter_id}" style="position:absolute; left:-9999px;" alt="" /></div></noscript>',
        METRIKA_END,
    ]
    return "\n".join(lines)


def apply_metrika_block(html_text, settings):
    start_idx = html_text.find(METRIKA_START)
    end_idx = html_text.find(METRIKA_END)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    new_html = html_text[:start_idx] + render_metrika_block(settings) + html_text[end_idx + len(METRIKA_END):]
    return new_html, True


def render_goals_block(settings):
    digits = re.sub(r"[^0-9]", "", settings.get("YANDEX_METRIKA_ID", ""))
    counter_id = digits if digits else "00000000"

    goal_names = {
        key.replace("GOAL_", "").lower(): (settings.get(key, "").strip() or default)
        for key, default in GOAL_KEYS.items()
    }
    # соответствие JS-ключей (telegram/yclients/...) настройкам prices.txt
    js_map = {
        "telegram": goal_names["telegram"],
        "yclients": goal_names["yclients"],
        "maps_yandex": goal_names["maps_yandex"],
        "maps_2gis": goal_names["maps_2gis"],
        "vk": goal_names["vk"],
        "phone": goal_names["phone"],
        "quiz": goal_names["quiz"],
    }
    goals_json = json.dumps(js_map, ensure_ascii=False)
    goals_json = goals_json.replace("</", "<\\/")

    lines = [
        GOALS_START,
        "<!-- Цели Яндекс.Метрики на переходы: Telegram, YClients (запись online), Яндекс Карты, 2ГИС,",
        "     VK-сообщество, звонок по телефону, а также заготовка для будущего квиза. Имена целей",
        "     задаются в prices.txt (раздел НАСТРОЙКИ, ключи GOAL_TELEGRAM / GOAL_YCLIENTS /",
        "     GOAL_MAPS_YANDEX / GOAL_MAPS_2GIS / GOAL_VK / GOAL_PHONE / GOAL_QUIZ) —",
        "     под такими же именами нужно завести цели типа «JavaScript-событие» в интерфейсе Метрики",
        "     (Настройки счётчика → Цели → Добавить цель → JavaScript-событие → вставить имя).",
        "     Общее число посетителей сайта отдельная цель не нужна — это уже считает сам счётчик. -->",
        '<script type="text/javascript">',
        "(function(){",
        f"  var MIO_GOALS = {goals_json};",
        f"  var MIO_COUNTER_ID = {counter_id};",
        "  function mioFireGoal(name){",
        '    try { if (typeof ym === "function" && name) { ym(MIO_COUNTER_ID, "reachGoal", name); } } catch (e) {}',
        "  }",
        "  // ручной вызов из кода — например, когда на сайте появится квиз:",
        "  // miolaserTrackGoal('quiz') в обработчике его завершения.",
        "  window.miolaserTrackGoal = function(key){",
        "    if (MIO_GOALS[key]) mioFireGoal(MIO_GOALS[key]);",
        "  };",
        "  function mioMatchGoalKey(href){",
        '    if (!href) return null;',
        '    if (href.indexOf("t.me/") !== -1) return "telegram";',
        '    if (href.indexOf("yclients.com") !== -1) return "yclients";',
        '    if (href.indexOf("yandex.ru/maps") !== -1 || href.indexOf("maps.yandex") !== -1) return "maps_yandex";',
        '    if (href.indexOf("2gis.ru") !== -1) return "maps_2gis";',
        '    if (href.indexOf("vk.com/") !== -1 || href.indexOf("vk.ru/") !== -1) return "vk";',
        '    if (href.indexOf("tel:") === 0) return "phone";',
        "    return null;",
        "  }",
        '  document.addEventListener("click", function(e){',
        '    var el = e.target && e.target.closest ? e.target.closest("[data-mio-goal],a[href]") : null;',
        "    if (!el) return;",
        '    var key = el.getAttribute("data-mio-goal");',
        '    if (!key) key = mioMatchGoalKey(el.getAttribute("href") || "");',
        "    if (key) window.miolaserTrackGoal(key);",
        "  }, true);",
        "})();",
        "</script>",
        GOALS_END,
    ]
    return "\n".join(lines)


def apply_goals_block(html_text, settings):
    start_idx = html_text.find(GOALS_START)
    end_idx = html_text.find(GOALS_END)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    new_html = html_text[:start_idx] + render_goals_block(settings) + html_text[end_idx + len(GOALS_END):]
    return new_html, True


def render_route_links(settings, indent, start_marker, end_marker):
    """Кнопки "Построить маршрут" (Яндекс.Карты / 2GIS) — ссылки собираются
    из GEO_LAT/GEO_LON в prices.txt, чтобы при смене адреса студии не нужно
    было руками лезть в HTML. Формат ссылок проверен вживую в браузере:
    Яндекс — открывает панель маршрута с заполненным "Куда"; 2GIS — тоже
    открывает построение маршрута (у 2GIS иногда обобщённая подпись точки,
    если у координат нет ID объекта в их базе — сам маршрут строится верно)."""
    lat = settings.get("GEO_LAT", "").strip()
    lon = settings.get("GEO_LON", "").strip()
    pad = " " * indent
    if not lat or not lon:
        # без координат — оставляем блок пустым, кнопки не будут работать,
        # но сайт не сломается
        return f"{pad}{start_marker}\n{pad}{end_marker}"
    yandex_url = f"https://yandex.ru/maps/?rtext=~{lat},{lon}&rtt=auto"
    dgis_url = f"https://2gis.ru/directions/points/|{lon},{lat}"
    lines = [
        start_marker,
        f'<a href="{html.escape(yandex_url)}" target="_blank" rel="noopener" data-mio-goal="maps_yandex"><span class="route-ico">Я</span>Яндекс.Карты</a>',
        f'<a href="{html.escape(dgis_url)}" target="_blank" rel="noopener" data-mio-goal="maps_2gis"><span class="route-ico">2</span>2GIS</a>',
        end_marker,
    ]
    return ("\n" + pad).join(lines)


def apply_route_links(html_text, settings, start_marker, end_marker):
    start_idx = html_text.find(start_marker)
    end_idx = html_text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    # определяем отступ по началу строки с меткой, чтобы не портить форматирование
    line_start = html_text.rfind("\n", 0, start_idx) + 1
    indent = start_idx - line_start
    new_html = (
        html_text[:start_idx]
        + render_route_links(settings, indent, start_marker, end_marker)
        + html_text[end_idx + len(end_marker):]
    )
    return new_html, True


def render_site_url_block(settings):
    site_url = settings.get("SITE_URL", "").strip()
    if not site_url:
        site_url = "https://miolaser.ru/"
    if not site_url.endswith("/"):
        site_url += "/"
    lines = [
        SITE_URL_START,
        f'<link rel="canonical" href="{html.escape(site_url)}">',
        f'<meta property="og:url" content="{html.escape(site_url)}">',
        f'<meta property="og:image" content="{html.escape(site_url)}images/og-cover.jpg">',
        "<!-- og-cover.jpg (1200×630) лежит в папке images/ рядом с miolaser-landing.html — при",
        "     публикации залейте всю папку images/ на хостинг вместе с сайтом, иначе ссылка в",
        "     Telegram/VK/WhatsApp будет расползаться без превью-картинки. -->",
        SITE_URL_END,
    ]
    return "\n".join(lines)


def apply_site_url_block(html_text, settings):
    start_idx = html_text.find(SITE_URL_START)
    end_idx = html_text.find(SITE_URL_END)
    if start_idx == -1 or end_idx == -1:
        return html_text, False
    new_html = html_text[:start_idx] + render_site_url_block(settings) + html_text[end_idx + len(SITE_URL_END):]
    return new_html, True


def make_backup(html_path):
    backups_dir = html_path.parent / "backups"
    backups_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = backups_dir / f"{html_path.stem}_{stamp}{html_path.suffix}"
    shutil.copy2(html_path, backup_path)
    # чистим старые копии, оставляем последние 20, чтобы папка не пухла бесконечно
    all_backups = sorted(backups_dir.glob(f"{html_path.stem}_*{html_path.suffix}"))
    for old in all_backups[:-20]:
        old.unlink(missing_ok=True)
    return backup_path


def main():
    print("=" * 60)
    print("Пересборка сайта MIOLASER из prices.txt")
    print("=" * 60)

    if not PRICES_PATH.exists():
        print(f'\nОШИБКА: не нашёл файл "{PRICES_PATH.name}" рядом со скриптом.')
        print("Убедитесь, что prices.txt лежит в той же папке, что и build_site.py.")
        sys.exit(1)

    if not HTML_PATH.exists():
        print(f'\nОШИБКА: не нашёл файл "{HTML_PATH.name}" рядом со скриптом.')
        print("Убедитесь, что miolaser-landing.html лежит в той же папке, что и build_site.py.")
        sys.exit(1)

    categories, settings, warnings, enc = parse_prices(PRICES_PATH)
    if enc != "utf-8-sig":
        print(f'(файл цен прочитан в кодировке {enc}, а не UTF-8 — на всякий случай пересохраните его как UTF-8)')

    if warnings:
        print(f"\nВНИМАНИЕ — нашёл {len(warnings)} возможных проблем в prices.txt:")
        for w in warnings:
            print("  ⚠ " + w)
        print("\nСайт всё равно соберу, но проверьте эти строки и перезапустите при необходимости.\n")

    html_text, html_enc = read_text_robust(HTML_PATH)
    if html_enc != "utf-8-sig":
        print(f'(файл сайта прочитан в кодировке {html_enc}, а не UTF-8 — сохраню результат уже в UTF-8)')

    start_idx = html_text.find(START_MARKER)
    end_idx = html_text.find(END_MARKER)
    if start_idx == -1 or end_idx == -1:
        print("\nОШИБКА: в HTML-файле не нашёл специальные метки PRICES:AUTO-START/END.")
        print("Похоже, файл miolaser-landing.html был изменён и повреждён — используйте")
        print("свежую копию, которую прислал Claude, либо обратитесь за помощью.")
        sys.exit(1)

    backup_path = make_backup(HTML_PATH)
    print(f"Резервная копия сайта сохранена: backups/{backup_path.name}")

    new_block = render_tabs_and_panels(categories)
    new_html = html_text[: start_idx + len(START_MARKER)] + "\n" + new_block + "\n      " + html_text[end_idx:]

    offers = render_offer_catalog(categories)
    new_html, ld_updated = update_json_ld(new_html, offers, settings)

    geo_updated = metrika_updated = site_url_updated = goals_updated = verify_updated = False
    route_hero_updated = route_contacts_updated = False
    if settings:
        new_html, geo_updated = apply_geo_block(new_html, settings)
        new_html, metrika_updated = apply_metrika_block(new_html, settings)
        new_html, site_url_updated = apply_site_url_block(new_html, settings)
        new_html, goals_updated = apply_goals_block(new_html, settings)
        new_html, verify_updated = apply_verification_block(new_html, settings)
        new_html, route_hero_updated = apply_route_links(new_html, settings, ROUTE_HERO_START, ROUTE_HERO_END)
        new_html, route_contacts_updated = apply_route_links(new_html, settings, ROUTE_CONTACTS_START, ROUTE_CONTACTS_END)

    HTML_PATH.write_text(new_html, encoding="utf-8")

    # robots.txt / sitemap.xml — техническая база для SEO/индексации, тоже
    # собираются из SITE_URL в prices.txt, чтобы не редактировать их руками
    # при смене домена. Пишутся рядом с сайтом, только если есть раздел
    # НАСТРОЙКИ (иначе неизвестен домен, писать было бы некуда/незачем).
    robots_written = sitemap_written = False
    if settings:
        site_url = settings.get("SITE_URL", "").strip() or "https://miolaser.ru"
        site_url = site_url.rstrip("/")
        robots_path = HTML_PATH.parent / "robots.txt"
        sitemap_path = HTML_PATH.parent / "sitemap.xml"
        robots_path.write_text(
            "User-agent: *\nAllow: /\n\nSitemap: " + site_url + "/sitemap.xml\n",
            encoding="utf-8",
        )
        robots_written = True
        today = datetime.date.today().isoformat()
        sitemap_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "  <url>\n"
            f"    <loc>{site_url}/</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            "    <changefreq>weekly</changefreq>\n"
            "    <priority>1.0</priority>\n"
            "  </url>\n"
            "</urlset>\n",
            encoding="utf-8",
        )
        sitemap_written = True

    total_items = sum(len(g["items"]) for c in categories for g in c["groups"])
    enabled_items = sum(1 for c in categories for g in c["groups"] for it in g["items"] if it["enabled"])

    print(f"\nГотово! Сайт обновлён: {HTML_PATH.name}")
    print(f"\nРазделы цен на сайте ({len(categories)}):")
    for c in categories:
        n_enabled = sum(1 for g in c["groups"] for it in g["items"] if it["enabled"])
        n_total = sum(len(g["items"]) for g in c["groups"])
        print(f'  - {c["title"]}: показано {n_enabled} из {n_total} услуг')
    print(f"\nВсего услуг в файле: {total_items}, показано на сайте: {enabled_items}")
    if not ld_updated:
        print("(SEO-список услуг (JSON-LD) не обновился — структура сайта могла измениться.)")

    if settings:
        print("\nГео-настройки (раздел НАСТРОЙКИ в prices.txt):")
        print(f'  - гео-метки на сайте: {"обновлены" if geo_updated else "НЕ найдены в HTML — сайт мог быть повреждён"}')
        print(f'  - счётчик Яндекс.Метрики: {"обновлён" if metrika_updated else "НЕ найден в HTML — сайт мог быть повреждён"}')
        print(f'  - адрес сайта (canonical/og:url/og:image): {"обновлён" if site_url_updated else "НЕ найден в HTML — сайт мог быть повреждён"}')
        print(f'  - цели Метрики (Telegram/YClients/Карты/2ГИС/VK/телефон/квиз): {"обновлены" if goals_updated else "НЕ найдены в HTML — сайт мог быть повреждён"}')
        print(f'  - кнопки "Построить маршрут" (hero): {"обновлены" if route_hero_updated else "НЕ найдены в HTML — сайт мог быть повреждён"}')
        print(f'  - кнопки "Построить маршрут" (контакты): {"обновлены" if route_contacts_updated else "НЕ найдены в HTML — сайт мог быть повреждён"}')
        print(f'  - код подтверждения Яндекс.Вебмастера: {"обновлён" if verify_updated else "НЕ найден в HTML — сайт мог быть повреждён"}')
        print(f'  - robots.txt: {"создан/обновлён" if robots_written else "не создан (нет раздела НАСТРОЙКИ)"}')
        print(f'  - sitemap.xml: {"создан/обновлён" if sitemap_written else "не создан (нет раздела НАСТРОЙКИ)"}')
        metrika_id = settings.get("YANDEX_METRIKA_ID", "").strip()
        if metrika_id in ("", "00000000"):
            print("  ⚠ номер счётчика Яндекс.Метрики пока не указан (стоит заглушка 00000000) —")
            print("    посещения сайта и переходы с геометок Яндекс.Бизнеса не будут собираться,")
            print("    пока вы не впишете реальный номер в YANDEX_METRIKA_ID (см. prices.txt).")
        if not settings.get("YANDEX_VERIFICATION", "").strip():
            print("  ⓘ код подтверждения в Яндекс.Вебмастере не указан (необязательно, но полезно —")
            print("    см. подсказку у YANDEX_VERIFICATION в prices.txt).")
    else:
        print("\n(В prices.txt не нашёл раздел НАСТРОЙКИ — гео-метки и счётчик Метрики не трогал,")
        print(" на сайте остались прежние значения.)")

    print("\nМожно открыть miolaser-landing.html в браузере и проверить результат.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nЧТО-ТО ПОШЛО НЕ ТАК: {e}")
        print("Если не получается разобраться — пришлите это сообщение и файл prices.txt в чат с Claude.")
        sys.exit(1)
