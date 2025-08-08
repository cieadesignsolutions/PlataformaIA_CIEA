from playwright.sync_api import sync_playwright
import os

SESSION_DIR = "whatsapp_session"

def main():
    os.makedirs(SESSION_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False para que puedas ver el QR
        context = browser.new_context(storage_state=f"{SESSION_DIR}/state.json")
        page = context.new_page()
        page.goto("https://web.whatsapp.com")

        print("\n🔄 Escanea el código QR desde tu celular.")
        print("⏳ Esperando inicio de sesión...")

        # Esperamos a que aparezca el selector de chats, lo que indica que ya inició sesión
        page.wait_for_selector("div[aria-label='Chat list']", timeout=180000)  # 3 minutos

        # Guardamos sesión
        context.storage_state(path=f"{SESSION_DIR}/state.json")
        print("✅ Sesión guardada correctamente en whatsapp_session/state.json")

        browser.close()

if __name__ == "__main__":
    main()
