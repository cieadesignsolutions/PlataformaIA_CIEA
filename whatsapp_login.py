from playwright.sync_api import sync_playwright
import os

SESSION_DIR = "whatsapp_session"

def main():
    if not os.path.exists(SESSION_DIR):
        os.makedirs(SESSION_DIR)

    with sync_playwright() as p:
        print("Abriendo navegador para escanear QR...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://web.whatsapp.com/")
        print("Escanea el código QR con tu número personal...")
        input("Presiona Enter una vez que WhatsApp haya cargado completamente...")

        # Guardar sesión
        context.storage_state(path=f"{SESSION_DIR}/state.json")
        print(f"Sesión guardada correctamente en {SESSION_DIR}/state.json")
        browser.close()

if __name__ == "__main__":
    main()
