// Your First C++ Program

#include <iostream>
#include <vector>
#include <numeric>
#include <algorithm>
#include <random>
#include <cstdlib>

int main(int argc, char *argv[])
{
    int nHands = 797500;
    if (argc >= 2)
    {
        nHands = atoi(argv[1]);
    }
    std::cout << "Simulating " << nHands << " hands." << std::endl;

    std::vector<int> deck(52);
    std::iota(deck.begin(), deck.end(), 0);
    // std::cout << "Deck is: ";
    // for (auto i = deck.begin(); i != deck.end(); ++i)
    //     std::cout << *i << ' ';
    // std::cout << std::endl;

    std::vector<int> deal(8);

    auto mt19937 = std::mt19937{std::random_device{}()};
    for (auto hand = 0; hand < nHands; ++hand)
    {
        std::sample(deck.begin(), deck.end(), deal.begin(), 8, mt19937);

        // std::cout << "Deal is: ";
        // for (auto i = deal.begin(); i != deal.end(); ++i)
        //     std::cout << *i << ' ';
        // std::cout << std::endl;
    }

    return 0;
}