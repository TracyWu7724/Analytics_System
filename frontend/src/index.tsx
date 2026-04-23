import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);

root.render(
  // Remove StrictMode to prevent double execution in development
  // <React.StrictMode>
    <App />
  // </React.StrictMode>
); 