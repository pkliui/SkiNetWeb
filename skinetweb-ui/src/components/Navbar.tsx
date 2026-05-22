import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";

const NAV_LINKS = [
  { label: "Documentation", href: "https://pkliui.github.io/SkiNet/" },
  { label: "About",         href: "https://www.linkedin.com/in/kliuiev/" },
];

const PAGE_LINKS = [
  { label: "Home",           to: "/" },
  { label: "Documentation",  to: "/documentation" },
  { label: "Network Design", to: "/network-design" },
];

const Navbar = () => {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <nav className="navbar">
      <span className="nav-brand">SkiNet</span>

      {/* Inline page navigation buttons */}
      <div className="nav-page-links">
        {PAGE_LINKS.map(({ label, to }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              isActive ? "nav-page-btn nav-page-btn--active" : "nav-page-btn"
            }
          >
            {label}
          </NavLink>
        ))}
      </div>

      {/* Hamburger menu — external links */}
      <div ref={menuRef} className="nav-menu-container">
        <button
          className="hamburger-btn"
          onClick={() => setMenuOpen((open) => !open)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
        >
          <span /><span /><span />
        </button>

        {menuOpen && (
          <div className="nav-menu" role="menu">
            {NAV_LINKS.map(({ label, href }) => (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                role="menuitem"
                onClick={() => setMenuOpen(false)}
              >
                {label}
              </a>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
};

export default Navbar;
