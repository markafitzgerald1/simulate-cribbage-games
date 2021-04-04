import React from "react";
import { Helmet } from "react-helmet";

const TitleAndH1: React.FunctionComponent<{ title: string }> = (
  props
): JSX.Element => (
  <div>
    <Helmet>
      <title>{props.title}</title>
    </Helmet>
    <h1>{props.title}</h1>
  </div>
);

export default TitleAndH1;
