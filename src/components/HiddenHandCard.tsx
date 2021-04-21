/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import { card } from "./Card.module.css";
import { hiddenHandCard } from "./HiddenHandCard.module.css";

const HiddenHandCard: React.FunctionComponent<{
  card: Card;
}> = (props): JSX.Element => <li className={`${card}  ${hiddenHandCard}`}></li>;

export default HiddenHandCard;
