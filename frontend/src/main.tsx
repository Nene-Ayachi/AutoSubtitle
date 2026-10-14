import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import App from "./App";
import "./style.css";
const theme = createTheme({
  palette: { primary: { main: "#2465bd" }, background: { default: "#f3f5f8" } },
  typography: { fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif' },
  shape: { borderRadius: 8 },
  components: { MuiButton: { defaultProps: { disableElevation: true } } },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>,
);
