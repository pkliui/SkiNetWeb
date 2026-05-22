import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./App.css";

import Navbar              from "./components/Navbar";
import HomePage            from "./pages/HomePage";
import DocumentationPage   from "./pages/DocumentationPage";
import NetworkDesignPage   from "./pages/NetworkDesignPage";

const App = () => (
  <BrowserRouter>
    <Navbar />
    <Routes>
      <Route path="/"               element={<HomePage />} />
      <Route path="/documentation"  element={<DocumentationPage />} />
      <Route path="/network-design" element={<NetworkDesignPage />} />
      <Route path="*"               element={<Navigate to="/" replace />} />
    </Routes>
  </BrowserRouter>
);

export default App;
