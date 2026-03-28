import React, { useEffect, useState } from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";

const SESSION_STORAGE_KEY = "my_chat_bot_web_session_token";

function getSessionToken() {
  return window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
}

function storeSessionToken(payload) {
  if (payload && typeof payload.sessionToken === "string" && payload.sessionToken) {
    window.localStorage.setItem(SESSION_STORAGE_KEY, payload.sessionToken);
  }
}

function buildHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const sessionToken = getSessionToken();
  if (sessionToken) {
    headers["X-Session-Token"] = sessionToken;
  }
  return headers;
}

function App() {
  const [state, setState] = useState({ linkedTelegramUserId: null, memoryUserId: null, messages: [] });
  const [message, setMessage] = useState("");
  const [linkCode, setLinkCode] = useState("");
  const [files, setFiles] = useState([]);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    refreshState();
  }, []);

  async function refreshState() {
    const response = await fetch("/api/state", { headers: buildHeaders() });
    const payload = await response.json();
    storeSessionToken(payload);
    setState(payload);
  }

  async function submitLink(event) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const response = await fetch("/api/link", {
        method: "POST",
        headers: buildHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ code: linkCode }),
      });
      const payload = await response.json();
      storeSessionToken(payload);
      if (!response.ok) {
        throw new Error(payload.error || "Не удалось привязать Telegram.");
      }
      setLinkCode("");
      await refreshState();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setPending(false);
    }
  }

  async function submitMessage(event) {
    event.preventDefault();
    if (!message.trim() && files.length === 0) {
      return;
    }
    setError("");
    setPending(true);
    try {
      const attachments = await Promise.all(files.map((file) => toAttachmentPayload(file)));
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: buildHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ message, attachments }),
      });
      const payload = await response.json();
      storeSessionToken(payload);
      if (!response.ok) {
        throw new Error(payload.error || "Не удалось отправить сообщение.");
      }
      setMessage("");
      setFiles([]);
      setFileInputKey((value) => value + 1);
      await refreshState();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setPending(false);
    }
  }

  return React.createElement(
    "div",
    { className: "page" },
    React.createElement(
      "section",
      { className: "hero" },
      React.createElement("h1", null, "thefem.ru"),
      React.createElement(
        "p",
        null,
        "Web-вход в того же ассистента. Можно использовать отдельную web-память или привязать браузер к Telegram и разделять общую память."
      )
    ),
    React.createElement(
      "div",
      { className: "grid" },
      React.createElement(
        "aside",
        { className: "card" },
        React.createElement("h2", null, "Память"),
        React.createElement(
          "div",
          { className: "status" },
          state.linkedTelegramUserId
            ? `Привязано к Telegram: ${state.linkedTelegramUserId}`
            : "Отдельный web-пользователь"
        ),
        React.createElement("p", { className: "muted", style: { marginTop: "12px" } }, `memory_user_id: ${state.memoryUserId ?? "..."}`),
        React.createElement(
          "form",
          { onSubmit: submitLink, style: { marginTop: "18px" } },
          React.createElement("label", { className: "label" }, "Код из Telegram команды /link"),
          React.createElement("input", {
            value: linkCode,
            onChange: (event) => setLinkCode(event.target.value.toUpperCase()),
            placeholder: "ABCD-1234",
          }),
          React.createElement(
            "div",
            { className: "actions" },
            React.createElement("button", { type: "submit", disabled: pending || !linkCode.trim() }, "Привязать")
          )
        ),
        React.createElement(
          "p",
          { className: "muted", style: { marginTop: "18px", fontSize: "0.95rem" } },
          "Если код не вводить, браузер будет работать как отдельный пользователь со своей памятью."
        )
      ),
      React.createElement(
        "main",
        { className: "card" },
        React.createElement("h2", null, "Чат"),
        React.createElement(
          "div",
          { className: "messages" },
          state.messages.length === 0
            ? React.createElement("p", { className: "muted" }, "История текущей активной web-сессии пока пуста.")
            : state.messages.map((item, index) =>
                React.createElement(
                  "div",
                  { key: `${item.role}-${index}`, className: `bubble ${item.role}` },
                  item.text
                )
              )
        ),
        React.createElement(
          "form",
          { onSubmit: submitMessage, style: { marginTop: "18px" } },
          React.createElement("label", { className: "label" }, "Сообщение"),
          React.createElement("textarea", {
            value: message,
            onChange: (event) => setMessage(event.target.value),
            placeholder: "Введите сообщение...",
          }),
          React.createElement("label", { className: "label", style: { marginTop: "14px" } }, "Вложения"),
          React.createElement("input", {
            key: fileInputKey,
            type: "file",
            multiple: true,
            onChange: (event) => setFiles(Array.from(event.target.files || [])),
          }),
          files.length > 0
            ? React.createElement(
                "p",
                { className: "muted", style: { marginTop: "10px", fontSize: "0.95rem" } },
                files.map((file) => file.name).join(", ")
              )
            : null,
          React.createElement(
            "p",
            { className: "muted", style: { marginTop: "10px", fontSize: "0.95rem" } },
            "Поддерживаются изображения, PDF, DOC, DOCX, XLSX и текстовые файлы."
          ),
          React.createElement(
            "div",
            { className: "actions" },
            React.createElement(
              "button",
              { type: "submit", disabled: pending || (!message.trim() && files.length === 0) },
              pending ? "Отправка..." : "Отправить"
            ),
            React.createElement(
              "button",
              {
                type: "button",
                className: "ghost",
                onClick: refreshState,
                disabled: pending,
              },
              "Обновить"
            )
          ),
          error ? React.createElement("p", { className: "error" }, error) : null
        )
      )
    )
  );
}

createRoot(document.getElementById("root")).render(React.createElement(App));

async function toAttachmentPayload(file) {
  const dataUrl = await readFileAsDataUrl(file);
  const commaIndex = dataUrl.indexOf(",");
  return {
    filename: file.name,
    mimeType: file.type || "application/octet-stream",
    dataBase64: commaIndex >= 0 ? dataUrl.slice(commaIndex + 1) : dataUrl,
  };
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`Не удалось прочитать файл ${file.name}.`));
    reader.readAsDataURL(file);
  });
}
