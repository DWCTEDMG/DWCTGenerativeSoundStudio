import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/app.css";
import { StudioAppearanceProvider } from "./components/studioAppearance";
import { UiModeProvider } from "./components/uiMode";
import { StudioSessionProvider } from "./components/studioSession";
import { ensureBrowserBridge } from "./components/api";

ensureBrowserBridge();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <StudioSessionProvider>
      <StudioAppearanceProvider>
        <UiModeProvider>
          <App />
        </UiModeProvider>
      </StudioAppearanceProvider>
    </StudioSessionProvider>
  </React.StrictMode>
);
