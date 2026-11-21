import React from "react";
import {AbsoluteFill, interpolate, staticFile, useCurrentFrame} from "remotion";
import {ALASKA_PATH} from "./alaskaPath";

const FPS = 30;
const SCENE_2 = Math.round(8.34 * FPS);
const SCENE_3 = Math.round(14.46 * FPS);
const FADE = 8;

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

const ink = "#17202b";
const paper = "#f6f1e8";
const muted = "#5d6b78";
const peltola = "#2f5f8a";
const sullivan = "#8a4a46";

export const AlaskaReel: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{backgroundColor: "#10161d", color: ink}}>
      <style>{fontFace}</style>
      <Layer frame={frame} start={0} end={SCENE_2} fadeIn={false} fadeOut>
        <MapScene />
      </Layer>
      <Layer frame={frame} start={SCENE_2 - FADE} end={SCENE_3} fadeIn fadeOut>
        <VoteScene frame={frame} start={SCENE_2 - FADE} />
      </Layer>
      <Layer frame={frame} start={SCENE_3 - FADE} end={543} fadeIn fadeOut={false}>
        <CloseScene frame={frame} />
      </Layer>
      <Disclaimer />
      <Subtitle frame={frame} />
    </AbsoluteFill>
  );
};

const Layer: React.FC<{
  frame: number;
  start: number;
  end: number;
  fadeIn: boolean;
  fadeOut: boolean;
  children: React.ReactNode;
}> = ({frame, start, end, fadeIn, fadeOut, children}) => {
  if (frame < start || frame >= end) {
    return null;
  }
  let opacity = 1;
  if (fadeIn) {
    opacity = Math.min(
      opacity,
      interpolate(frame, [start, start + FADE], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
    );
  }
  if (fadeOut) {
    opacity = Math.min(
      opacity,
      interpolate(frame, [end - FADE, end], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
    );
  }
  return <AbsoluteFill style={{opacity}}>{children}</AbsoluteFill>;
};

const Safe: React.FC<{children: React.ReactNode; top?: number}> = ({children, top = 320}) => (
  <div
    style={{
      position: "absolute",
      top,
      left: 88,
      right: 170,
      direction: "rtl",
      fontFamily: "Vazirmatn, sans-serif",
      textAlign: "center",
    }}
  >
    {children}
  </div>
);

const MapScene: React.FC = () => (
  <AbsoluteFill>
    <Safe>
      <div style={{fontSize: 78, fontWeight: 700, lineHeight: 1.25, color: paper}}>۱۷ نوامبر</div>
      <div style={{marginTop: 8, fontSize: 48, fontWeight: 700, lineHeight: 1.35, color: paper}}>
        آسوشیتد پرس پلتولا را
        <br />
        برنده سنای آلاسکا خواند
      </div>
    </Safe>
    <div
      style={{
        position: "absolute",
        top: 620,
        left: 88,
        right: 170,
        direction: "rtl",
        textAlign: "center",
        fontFamily: "Vazirmatn, sans-serif",
        fontSize: 32,
        color: "#d5dde6",
      }}
    >
      محدوده ایالت، بدون علامت شهر
    </div>
    <div style={{position: "absolute", top: 680, left: 249, width: 500, height: 594}}>
      <svg viewBox="0 0 640 760" width="500" height="594">
        <path d={ALASKA_PATH} fill="#d5e2ee" stroke="#9eb4c8" strokeWidth={3} strokeLinejoin="round" />
      </svg>
    </div>
  </AbsoluteFill>
);

const VoteScene: React.FC<{frame: number; start: number}> = ({frame, start}) => {
  const grow = interpolate(frame - start, [8, 24], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <Safe top={320}>
        <div style={{fontSize: 72, fontWeight: 700, lineHeight: 1.25, color: paper}}>رأی اول</div>
        <div style={{marginTop: 10, fontSize: 36, color: "#d5dde6"}}>همان درصدهای گزارش‌شده</div>
      </Safe>
      <div style={{position: "absolute", top: 620, left: 88, right: 170, direction: "rtl", fontFamily: "Vazirmatn, sans-serif"}}>
        <Bar name="پلتولا" figure="۵۰٫۱٪" value={50.1 * grow} color={peltola} />
        <Bar name="سالیوان" figure="۴۵٫۸٪" value={45.8 * grow} color={sullivan} />
        <div style={{marginTop: 28, textAlign: "center", fontSize: 30, color: muted}}>محور از صفر تا صد</div>
      </div>
    </AbsoluteFill>
  );
};

const Bar: React.FC<{name: string; figure: string; value: number; color: string}> = ({name, figure, value, color}) => (
  <div style={{marginTop: 54}}>
    <div style={{display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14}}>
      <div style={{fontSize: 64, fontWeight: 700, color: paper}}>{figure}</div>
      <div style={{fontSize: 52, fontWeight: 700, color: paper}}>{name}</div>
    </div>
    <div style={{height: 56, borderRadius: 10, backgroundColor: "#243140", overflow: "hidden", direction: "ltr"}}>
      <div style={{width: `${value}%`, height: "100%", backgroundColor: color}} />
    </div>
  </div>
);

const CloseScene: React.FC<{frame: number}> = ({frame}) => {
  const rise = interpolate(frame, [SCENE_3 - FADE, SCENE_3 + 6], [18, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill>
      <Safe top={520}>
        <div style={{transform: `translateY(${rise}px)`}}>
          <div style={{fontSize: 44, fontWeight: 700, color: "#d5dde6"}}>۱۹ نوامبر</div>
          <div style={{marginTop: 28, fontSize: 92, fontWeight: 700, lineHeight: 1.25, color: paper}}>
            نتیجه هنوز
            <br />
            رسمی نیست
          </div>
          <div style={{marginTop: 36, fontSize: 36, lineHeight: 1.5, color: "#d5dde6"}}>
            اعلام آسوشیتد پرس مانده است
            <br />
            تأیید ایالت در این تاریخ انجام نشده بود
          </div>
        </div>
      </Safe>
    </AbsoluteFill>
  );
};

const Disclaimer: React.FC = () => (
  <div
    style={{
      position: "absolute",
      top: 250,
      left: 88,
      right: 170,
      direction: "rtl",
      textAlign: "center",
      fontFamily: "Vazirmatn, sans-serif",
      fontSize: 28,
      lineHeight: 1.4,
      color: "#c5ced6",
    }}
  >
    طرح خبری است، نه عکس رویداد
  </div>
);

const cues = [
  {lines: ["۱۷ نوامبر، آسوشیتد پرس"], start: 0.05, end: 2.62},
  {lines: ["مری پلتولا را مقابل", "جمهوری‌خواه دن سالیوان"], start: 2.62, end: 5.68},
  {lines: ["برنده سنای آلاسکا اعلام کرد."], start: 5.68, end: 8.34},
  {lines: ["رأی اول حدود ۵۰٫۱ درصد", "در برابر ۴۵٫۸ درصد بود،"], start: 8.599, end: 14.46},
  {lines: ["و تا ۱۹ نوامبر", "نتیجه رسمی نشده بود."], start: 14.688, end: 18.1},
];

const Subtitle: React.FC<{frame: number}> = ({frame}) => {
  const time = frame / FPS;
  const cue = cues.find((item) => time >= item.start && time < item.end);
  if (!cue) {
    return null;
  }
  return (
    <div
      style={{
        position: "absolute",
        left: 72,
        right: 150,
        bottom: 450,
        direction: "rtl",
        textAlign: "center",
        fontFamily: "Vazirmatn, sans-serif",
      }}
    >
      <div
        style={{
          display: "inline-block",
          maxWidth: "100%",
          backgroundColor: "rgba(16, 22, 29, 0.92)",
          color: paper,
          fontSize: 46,
          fontWeight: 700,
          lineHeight: 1.45,
          padding: "22px 28px",
          borderRadius: 18,
        }}
      >
        {cue.lines.map((line) => (
          <div key={line}>{line}</div>
        ))}
      </div>
    </div>
  );
};
