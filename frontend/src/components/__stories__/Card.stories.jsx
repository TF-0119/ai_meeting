import Card from "../Card";
import Button from "../Button";

export default {
  title: "Components/Card",
  component: Card,
  args: {
    title: "カードの見出し",
    description: "補足説明として利用します。",
  },
};

export const Basic = {
  args: {
    children: (
      <p>
        このカードはセクションをまとめるのに使います。背景コントラストはライト/ダークの両テーマで
        WCAG を満たすように設計されています。
      </p>
    ),
  },
};

export const WithActions = {
  args: {
    children: <p>アクションボタンは footer に配置されます。</p>,
    actions: (
      <>
        <Button variant="ghost">キャンセル</Button>
        <Button>保存</Button>
      </>
    ),
  },
};
