import Card from "./Card";
import { Engine, sample } from "random-js";
import Hand from "./Hand";

const DEALT_HAND_SIZE = 4;

export default (randomJsEngine: Engine, deck: Card[]): Hand =>
  new Hand(sample(randomJsEngine, deck, DEALT_HAND_SIZE));
