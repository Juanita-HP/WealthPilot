import { useCallback, useEffect, useState } from "react";
import { ApiError, api, getToken, go, setToken } from "./lib.js";
import Auth from "./pages/Auth.jsx";
import Onboarding from "./pages/Onboarding.jsx";
import Home from "./pages/Home.jsx";
import Research from "./pages/Research.jsx";
import Watchlist from "./pages/Watchlist.jsx";
import Plan from "./pages/Plan.jsx";
import TimeMachine from "./pages/TimeMachine.jsx";
import Advocate from "./pages/Advocate.jsx";
import Lab from "./pages/Lab.jsx";
import Profile from "./pages/Profile.jsx";

// Hash routes: #/ (search), #/stock/NVDA, #/watchlist, #/plan, #/time-machine, #/advocate, #/lab, #/profile, #/onboarding
function parseRoute() {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return { page: parts[0] || "stocks", arg: parts[1] || "" };
}


const NAV = [["stocks", "Stocks"], ["watchlist", "Watchlist"], ["plan", "My plan"], ["time-machine", "Time machine"],
             ["advocate", "Devil's advocate"]];

export default function App() {
  const [route, setRoute] = useState(parseRoute());
  const [me, setMe] = useState(null);           // {username, has_profile}
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [profileVersion, setProfileVersion] = useState(0);

  useEffect(() => {
    const onHash = () => { setRoute(parseRoute()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const refreshMe = useCallback(async () => {
    if (!getToken()) { setMe(null); setChecking(false); return; }
    try { setMe(await api("/me")); }
    catch (e) { if (e instanceof ApiError && e.status === 401) setToken(""); setMe(null); }
    finally { setChecking(false); }
  }, []);

  useEffect(() => { refreshMe(); }, [refreshMe]);

  const signOut = () => { setToken(""); setMe(null); go("stocks"); };
  const profileSaved = async () => { setProfileVersion(v => v + 1); await refreshMe(); go("plan"); };

  if (checking) return <div className="app"><main><div className="loading">Loading…</div></main></div>;

  let content;
  let fullscreen = false;
  if (!me) {
    fullscreen = true;
    content = <Auth onSignedIn={async token => { setToken(token); await refreshMe(); }} />;
  } else if (!me.has_profile || route.page === "onboarding") {
    fullscreen = true;
    content = <Onboarding editing={me.has_profile} onSaved={profileSaved}
                          onCancel={me.has_profile ? () => go("profile") : null} />;
  } else {
    const key = profileVersion;
    content = {
      stocks: route.arg ? <Research key={route.arg + key} symbol={route.arg} /> : <Home key={key} />,
      stock: <Research key={route.arg + key} symbol={route.arg} />,
      watchlist: <Watchlist />,
      plan: <Plan key={key} />,
      "time-machine": <TimeMachine key={key} />,
      advocate: <Advocate key={key} />,
      lab: <Lab key={key} />,
      profile: <Profile key={key} username={me.username} onChanged={() => setProfileVersion(v => v + 1)}
                        onSignOut={signOut} onDeleted={refreshMe} />,
    }[route.page] || <Home />;
  }
  const active = route.page === "stock" ? "stocks" : route.page;

  return (
    <div className={"app" + (fullscreen ? " fullscreen" : "")}>
      <header>
        <div className="brand" onClick={() => go("stocks")}>
          <div className="logo"><i></i><i></i><i></i></div>
          <strong>WealthPilot</strong>
        </div>
        <nav>
          {NAV.map(([page, label]) => (
            <button key={page} className={active === page ? "active" : ""} onClick={() => go(page)}>{label}</button>
          ))}
        </nav>
        <button className="profile" aria-label="Investor profile" title="Investor profile" onClick={() => go("profile")}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="8" r="3.5" />
            <path d="M5 20c0-4 3-6 7-6s7 2 7 6" />
          </svg>
        </button>
      </header>
      <div className="disclaimer">Educational simulation · fictional accounts and amounts · no real trades · not financial advice</div>
      <main>{content}</main>
    </div>
  );
}
