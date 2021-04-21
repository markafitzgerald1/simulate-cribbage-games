/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

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
