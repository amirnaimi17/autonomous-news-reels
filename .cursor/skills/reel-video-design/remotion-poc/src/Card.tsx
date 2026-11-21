import React from "react";
import {AbsoluteFill, interpolate, staticFile, useCurrentFrame} from "remotion";

const fontFace = `
@font-face {
  font-family: "Vazirmatn";
  src: url("${staticFile("Vazirmatn-Regular.ttf")}") format("truetype");
  font-weight: 400;
}
`;

export const Card: React.FC = () => {
  const frame = useCurrentFrame();
  const peltola = interpolate(frame, [8, 36], [0, 50.1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const sullivan = interpolate(frame, [8, 36], [0, 45.8], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const titleY = interpolate(frame, [0, 16], [24, 0], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{backgroundColor: "#172033", color: "#f4efe6"}}>
      <style>{fontFace}</style>
      <AbsoluteFill
        style={{
          direction: "rtl",
          fontFamily: "Vazirmatn, sans-serif",
          padding: "160px 88px",
          transform: `translateY(${titleY}px)`,
        }}
      >
        <div style={{fontSize: 64, lineHeight: 1.4}}>سنای آلاسکا</div>
        <div style={{marginTop: 18, fontSize: 34, opacity: 0.8}}>طرح داده‌ای، نه عکس رویداد</div>
        <Bar label="پلتولا" value={peltola} color="#7f93b0" />
        <Bar label="سالیوان" value={sullivan} color="#9a5a55" />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Bar: React.FC<{label: string; value: number; color: string}> = ({label, value, color}) => {
  return (
    <div style={{marginTop: 64}}>
      <div style={{fontSize: 36, marginBottom: 14}}>{label}</div>
      <div style={{height: 42, backgroundColor: "#243044", borderRadius: 8, overflow: "hidden"}}>
        <div style={{width: `${value}%`, height: "100%", backgroundColor: color}} />
      </div>
    </div>
  );
};
