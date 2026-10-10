"""
Secure URL and input validation for EXU URL-to-App Converter.
"""
import re
import ipaddress
from urllib.parse import urlparse, urlunparse
import validators
import requests
from bs4 import BeautifulSoup

# Blocked schemes and hosts
BLOCKED_SCHEMES = {"file", "ftp", "javascript", "data", "vbscript"}
PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

APP_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 _\-\.]{1,48}[a-zA-Z0-9]$")
PACKAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
COLOR_PATTERN = re.compile(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")


def is_private_or_local(host: str) -> bool:
    """Return True if host resolves to private/local IP or is localhost."""
    host = host.lower().strip(".")
    if host in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
        return True
    try:
        # Try as IP first
        ip = ipaddress.ip_address(host)
        for net in PRIVATE_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        # Not an IP — check common internal host patterns
        if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan"):
            return True
        return False


def sanitize_url(url: str) -> str | None:
    """
    Validate and normalize a URL.
    Returns cleaned URL or None if invalid/unsafe.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if len(url) > 2048:
        return None

    # Add scheme if missing
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    if not validators.url(url):
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if scheme in BLOCKED_SCHEMES:
        return None

    host = parsed.hostname
    if not host:
        return None

    if is_private_or_local(host):
        return None

    # Rebuild clean URL (strip fragments, normalize)
    clean = urlunparse((
        scheme,
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.params,
        parsed.query,
        ""  # no fragment
    ))
    return clean


def validate_app_name(name: str) -> tuple[bool, str]:
    if not name or not isinstance(name, str):
        return False, "App name is required"
    name = name.strip()
    if len(name) < 2 or len(name) > 50:
        return False, "App name must be 2–50 characters"
    if not APP_NAME_PATTERN.match(name):
        return False, "App name contains invalid characters"
    return True, name


def validate_package_name(pkg: str) -> tuple[bool, str]:
    if not pkg:
        return True, "com.exu.app"  # default
    pkg = pkg.strip().lower()
    if not PACKAGE_PATTERN.match(pkg):
        return False, "Invalid package name (e.g. com.company.app)"
    if len(pkg) > 100:
        return False, "Package name too long"
    return True, pkg


def validate_color(color: str, default: str = "#6366f1") -> str:
    if not color:
        return default
    color = color.strip()
    if COLOR_PATTERN.match(color):
        return color if len(color) == 7 else f"#{color[1]*2}{color[2]*2}{color[3]*2}"
    return default


def fetch_site_metadata(url: str, timeout: int = 8) -> dict:
    """
    Safely fetch title, description, favicon from the target URL.
    Returns dict with keys: title, description, favicon, ok, error
    """
    result = {
        "title": "",
        "description": "",
        "favicon": "",
        "ok": False,
        "error": None,
    }
    try:
        headers = {
            "User-Agent": "EXU-URL-to-App/1.0 (+https://exu.app; metadata-fetcher)",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
        # Limit body size
        content = b""
        for chunk in resp.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > 512_000:  # 512 KB max
                break
        resp.raise_for_status()

        soup = BeautifulSoup(content, "lxml")
        title_tag = soup.find("title")
        result["title"] = (title_tag.get_text(strip=True)[:80] if title_tag else "") or ""

        desc = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        if desc and desc.get("content"):
            result["description"] = desc["content"].strip()[:200]

        # Favicon
        icon = (
            soup.find("link", rel=lambda x: x and "icon" in x.lower())
            or soup.find("link", rel="shortcut icon")
        )
        if icon and icon.get("href"):
            fav = icon["href"]
            if fav.startswith("//"):
                fav = "https:" + fav
            elif fav.startswith("/"):
                parsed = urlparse(url)
                fav = f"{parsed.scheme}://{parsed.netloc}{fav}"
            elif not fav.startswith("http"):
                parsed = urlparse(url)
                fav = f"{parsed.scheme}://{parsed.netloc}/{fav.lstrip('/')}"
            result["favicon"] = fav

        result["ok"] = True
    except requests.Timeout:
        result["error"] = "Timeout while fetching site metadata"
    except requests.RequestException as e:
        result["error"] = f"Could not fetch site: {str(e)[:100]}"
    except Exception as e:
        result["error"] = f"Metadata error: {str(e)[:100]}"
    return result
