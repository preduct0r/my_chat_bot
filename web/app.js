import React, { useEffect, useRef, useState } from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";
import { shouldSubmitOnEnter } from "/app_logic.js";

function App() {
  const [state, setState] = useState({ messages: [] });
  const [message, setMessage] = useState("");
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  useEffect(() => {
    refreshState();
  }, []);

  async function refreshState() {
    const response = await fetch("/api/state", { credentials: "include" });
    const payload = await response.json();
    setState(payload);
  }

  async function submitMessage(event) {
    event.preventDefault();
    if (!message.trim() && selectedFiles.length === 0) {
      return;
    }
    setError("");
    setPending(true);
    try {
      const formData = new FormData();
      formData.append("message", message);
      for (const file of selectedFiles) {
        formData.append("files", file);
      }
      const response = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Не удалось отправить сообщение.");
      }
      setMessage("");
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshState();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setPending(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (
      shouldSubmitOnEnter({
        key: event.key,
        shiftKey: event.shiftKey,
        pending,
        hasMessage: Boolean(message.trim()),
        hasFiles: selectedFiles.length > 0,
      })
    ) {
      event.preventDefault();
      submitMessage(event);
    }
  }

  return React.createElement(
    "div",
    { className: "page" },
    React.createElement(
      "section",
      { className: "hero" },
      React.createElement("h1", null, "Виртуальный помощник"),
      React.createElement(
        "p",
        null,
        "Бот принимает запросы на любые темы, может поддерживать диалог и выступать в роли специалиста практически в любой области. Он также умеет запоминать контекст ваших прошлых разговоров."
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
          onKeyDown: handleComposerKeyDown,
          placeholder: "Введите сообщение...",
        }),
        React.createElement("label", { className: "label", style: { marginTop: "16px" } }, "Документы и файлы"),
        React.createElement("input", {
          ref: fileInputRef,
          type: "file",
          multiple: true,
          onChange: (event) => setSelectedFiles(Array.from(event.target.files || [])),
          accept: ".txt,.md,.json,.csv,.py,.js,.ts,.html,.css,.xml,.yaml,.yml,.pdf,.doc,.docx,.xls,.xlsx,image/*",
        }),
        React.createElement(
          "p",
          { className: "muted", style: { marginTop: "10px", fontSize: "0.95rem" } },
          selectedFiles.length > 0
            ? `Выбрано файлов: ${selectedFiles.map((file) => file.name).join(", ")}`
            : "Можно отправлять изображения, PDF, DOC, DOCX, XLSX и текстовые файлы."
        ),
        React.createElement(
          "div",
          { className: "actions" },
          React.createElement(
            "button",
            { type: "submit", disabled: pending || (!message.trim() && selectedFiles.length === 0) },
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
  );
}

createRoot(document.getElementById("root")).render(React.createElement(App));
