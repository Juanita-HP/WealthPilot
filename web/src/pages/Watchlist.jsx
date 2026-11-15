import { useState } from "react";
import { getWatchlist, saveWatchlist, go } from "../lib.js";

export default function Watchlist() {
  const [items, setItems] = useState(getWatchlist());
  const [error, setError] = useState("");

  const remove = symbol => {
    const remaining = getWatchlist().filter(saved => saved.symbol !== symbol);
    if (saveWatchlist(remaining)) setItems(remaining);
    else setError("Unable to save. Browser storage may be disabled.");
  };

  return (
    <section className="watchlist-page">
      <div className="watchlist-page-heading">
        <h1>My watchlist.</h1>
        <p>Your saved companies, all in one place.</p>
      </div>
      <div className="watchlist-items">
        {!items.length && (
          <div className="watchlist-empty">
            <div className="watchlist-empty-icon">☆</div>
            <h3>Your watchlist is empty</h3>
            <p>Research a company and click the star beside its name to save it here.</p>
          </div>
        )}
        {items.map(item => (
          <div className="watchlist-item" key={item.symbol}>
            <div className="watchlist-item-main" tabIndex={0} role="button" aria-label={"Open " + item.symbol}
                 onClick={() => go("stocks", item.symbol)}
                 onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go("stocks", item.symbol); } }}>
              <div className="watchlist-item-symbol">{item.symbol}</div>
              <div className="watchlist-item-name">{item.name}</div>
            </div>
            <button className="watchlist-remove" type="button" title="Remove from watchlist"
                    aria-label={"Remove " + item.symbol + " from watchlist"} onClick={() => remove(item.symbol)}>★</button>
          </div>
        ))}
      </div>
      <div className="watchlist-error">{error}</div>
    </section>
  );
}
