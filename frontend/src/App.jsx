import React from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Meeting from "./pages/Meeting.jsx";
import Result from "./pages/Result.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <nav className="nav">
          <NavLink to="/" className="nav-link">Home</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/meeting/:id" element={<Meeting />} />
          <Route path="/result/:id" element={<Result />} />
        </Routes>
      </main>
    </div>
  );
}