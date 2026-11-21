import React from "react";
import {Composition} from "remotion";
import {AlaskaReel} from "./AlaskaReel";
import {Card} from "./Card";
import {DataReel, dataReelDuration, type DataScene} from "./DataReel";
import {PHOTO_TICKET_FRAMES, PhotoTicketReel} from "./PhotoTicketReel";
import {TICKET_FRAMES, TicketReel} from "./TicketReel";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="NewsCard" component={Card} durationInFrames={60} fps={30} width={1080} height={1920} />
      <Composition id="AlaskaReel" component={AlaskaReel} durationInFrames={543} fps={30} width={1080} height={1920} />
      <Composition id="TicketReel" component={TicketReel} durationInFrames={TICKET_FRAMES} fps={30} width={1080} height={1920} />
      <Composition id="PhotoTicketReel" component={PhotoTicketReel} durationInFrames={PHOTO_TICKET_FRAMES} fps={30} width={1080} height={1920} />
      <Composition
        id="DataReel"
        component={DataReel}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{scenes: [] as DataScene[]}}
        calculateMetadata={({props}) => ({durationInFrames: dataReelDuration(props.scenes), props})}
      />
    </>
  );
};
