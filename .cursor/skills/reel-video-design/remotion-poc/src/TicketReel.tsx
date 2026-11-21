import React from "react";
import {AbsoluteFill, interpolate, staticFile, useCurrentFrame} from "remotion";

const FRAMES = [348, 456, 442, 552, 254, 207];
const TOTAL = FRAMES.reduce((sum, value) => sum + value, 0);
const NAVY = "#0B1F3A";
const YELLOW = "#F5C518";
const WHITE = "#FFFFFF";

const fontFace = `
@font-face {
  font-family: "Vazirmatn";
  src: url("${staticFile("Vazirmatn-Regular.ttf")}") format("truetype");
  font-weight: 400;
}
@font-face {
  font-family: "Vazirmatn";
  src: url("${staticFile("Vazirmatn-Bold.ttf")}") format("truetype");
  font-weight: 700;
}
`;

const starts = FRAMES.reduce<number[]>((items, _value, index) => {
  const previous = index === 0 ? 0 : items[index - 1] + FRAMES[index - 1];
  items.push(previous);
  return items;
}, []);

export const TicketReel: React.FC = () => {
  const frame = useCurrentFrame();
  const scene = starts.findIndex((start, index) => frame >= start && frame < start + FRAMES[index]);
  const active = scene === -1 ? FRAMES.length - 1 : scene;
  return (
    <AbsoluteFill style={{backgroundColor: NAVY, color: WHITE, fontFamily: "Vazirmatn, sans-serif"}}>
      <style>{fontFace}</style>
      <Ticket frame={frame} />
      {active === 0 ? <PriceScene frame={frame} /> : null}
      {active === 1 ? <DateScene /> : null}
      {active === 2 ? <RuleScene /> : null}
      {active === 3 ? <BahnScene /> : null}
      {active === 4 ? <BvgScene /> : null}
      {active === 5 ? <CloseScene /> : null}
      <Caption index={active} />
    </AbsoluteFill>
  );
};

const Ticket: React.FC<{frame: number}> = ({frame}) => {
  const rise = interpolate(frame, [0, 20], [24, 0], {extrapolateRight: "clamp"});
  return (
    <div
      style={{
        position: "absolute",
        top: 1180 + rise,
        left: 250,
        width: 500,
        height: 220,
        borderRadius: 28,
        border: `8px solid ${YELLOW}`,
        backgroundColor: "#102844",
      }}
    />
  );
};

const Block: React.FC<{children: React.ReactNode; top?: number}> = ({children, top = 250}) => (
  <div style={{position: "absolute", top, left: 88, right: 160, direction: "rtl", textAlign: "right"}}>
    {children}
  </div>
);

const PriceScene: React.FC<{frame: number}> = ({frame}) => {
  const grow = interpolate(frame, [12, 48], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <Block>
      <div style={{fontSize: 42, color: YELLOW}}>از اول ژانویه ۲۰۲۷</div>
      <div style={{marginTop: 36, fontSize: 92, fontWeight: 700, color: WHITE}}>۶۳</div>
      <div style={{height: 28, marginTop: 18, background: "#163154", borderRadius: 8}}>
        <div style={{width: `${grow * 63}%`, height: "100%", background: WHITE, borderRadius: 8}} />
      </div>
      <div style={{marginTop: 28, fontSize: 92, fontWeight: 700, color: YELLOW}}>۶۶٫۸۰</div>
      <div style={{height: 28, marginTop: 18, background: "#163154", borderRadius: 8}}>
        <div style={{width: `${grow * 66.8}%`, height: "100%", background: YELLOW, borderRadius: 8}} />
      </div>
      <div style={{marginTop: 18, fontSize: 36}}>یورو در ماه</div>
    </Block>
  );
};

const DateScene: React.FC = () => (
  <Block>
    <div style={{fontSize: 40, color: YELLOW}}>دولت فدرال، نوامبر ۲۰۲۶</div>
    <div style={{marginTop: 48, fontSize: 64, fontWeight: 700, lineHeight: 1.35}}>
      اجرا از
      <br />
      اول ژانویه ۲۰۲۷
    </div>
    <div style={{marginTop: 36, fontSize: 40, lineHeight: 1.5}}>اولین بار شاخص قیمت وزرای ترابری ایالت‌ها</div>
  </Block>
);

const RuleScene: React.FC = () => (
  <Block>
    <div style={{fontSize: 40, color: YELLOW}}>قاعده دولت فدرال</div>
    <div style={{marginTop: 36, fontSize: 48, fontWeight: 700, lineHeight: 1.45}}>اگر شرکت بخواهد، تأیید لازم است</div>
    <div style={{marginTop: 28, fontSize: 48, fontWeight: 700, lineHeight: 1.45, color: YELLOW}}>اگر تماس نگیرد، قیمت خودکار اعمال می‌شود</div>
  </Block>
);

const BahnScene: React.FC = () => (
  <Block>
    <div style={{fontSize: 42, color: YELLOW}}>فقط دویچه بان</div>
    <div style={{marginTop: 36, fontSize: 46, fontWeight: 700, lineHeight: 1.45}}>پاسخ تا ۳۰ نوامبر ۲۰۲۶</div>
    <div style={{marginTop: 18, fontSize: 40, lineHeight: 1.5}}>بدون پاسخ، پایان در ۳۱ دسامبر ۲۰۲۶</div>
    <div style={{marginTop: 18, fontSize: 40, lineHeight: 1.5}}>خرید از ۱۵ اکتبر ۲۰۲۶ تأیید جدا نمی‌خواهد</div>
  </Block>
);

const BvgScene: React.FC = () => (
  <Block>
    <div style={{fontSize: 42, color: YELLOW}}>فقط ب‌وی‌گ</div>
    <div style={{marginTop: 48, fontSize: 64, fontWeight: 700, lineHeight: 1.4}}>تأیید لازم نیست</div>
    <div style={{marginTop: 24, fontSize: 44}}>مبلغ خودکار به ۶۶٫۸۰ یورو می‌رسد</div>
  </Block>
);

const CloseScene: React.FC = () => (
  <Block top={280}>
    <div style={{fontSize: 64, fontWeight: 700, lineHeight: 1.45}}>قاعده هر فروشنده جداست</div>
    <div style={{marginTop: 36, fontSize: 46, color: YELLOW, lineHeight: 1.5}}>پیام همان شرکت را بخوان</div>
  </Block>
);

const CAPTIONS = [
  "از اول ژانویه ۲۰۲۷ قیمت ماهانه از ۶۳ یورو به ۶۶٫۸۰ یورو می‌رسد. این فقط خبر گرانی نیست.",
  "دولت فدرال این قیمت را برای اول ژانویه ۲۰۲۷ نوشته و می‌گوید شاخص ایالت‌ها اولین بار به کار می‌افتد.",
  "تأیید فقط وقتی لازم است که شرکت حمل‌ونقل آن را بخواهد. اگر تماسی نباشد، قیمت جدید خودکار است.",
  "دویچه بان تا ۳۰ نوامبر ۲۰۲۶ پاسخ می‌خواهد. خرید از ۱۵ اکتبر پیش خودش تأیید جدا نمی‌خواهد.",
  "ب‌وی‌گ می‌گوید برای اشتراک خودش تأیید لازم نیست.",
  "یک قاعده برای هر فروشنده نیست. پیام شرکت خودت را بخوان.",
];

const Caption: React.FC<{index: number}> = ({index}) => (
  <div
    style={{
      position: "absolute",
      left: 72,
      right: 160,
      bottom: 470,
      direction: "rtl",
      textAlign: "right",
      fontSize: 40,
      lineHeight: 1.45,
      color: WHITE,
      backgroundColor: "rgba(11,31,58,0.88)",
      borderRight: `8px solid ${YELLOW}`,
      padding: "16px 22px",
    }}
  >
    {CAPTIONS[index]}
  </div>
);

export const TICKET_FRAMES = TOTAL;
