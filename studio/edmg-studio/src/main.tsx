import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/app.css";
import { UiModeProvider } from "./components/uiMode";
import { StudioSessionProvider } from "./components/studioSession";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <StudioSessionProvider>
      <UiModeProvider>
        <App />
      </UiModeProvider>
    </StudioSessionProvider>
  </React.StrictMode>
);
