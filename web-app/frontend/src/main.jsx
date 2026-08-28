import React from "react";
import ReactDOM from "react-dom/client";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { HashRouter } from "react-router-dom";
import App from "./App";
import GlobalMessageProvider from "./components/GlobalMessageProvider";
import theme from "./theme";
import "./App.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <HashRouter>
        <GlobalMessageProvider>
          <App />
        </GlobalMessageProvider>
      </HashRouter>
    </ThemeProvider>
  </React.StrictMode>
);
