import React from "react";

// 進行中会議一覧の簡易プレースホルダー。
export default function Ongoing() {
  return (
    <div className="card">
      <h1 className="title">進行中の会議</h1>
      <p className="muted">
        現在進行中の会議はありません。会議が開始されるとここに表示されます。
      </p>
    </div>
  );
}
