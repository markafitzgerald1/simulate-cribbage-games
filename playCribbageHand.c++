// Your First C++ Program

#include <iostream>
#include <vector>
#include <numeric>
#include <algorithm>
#include <random>

int main()
{
    std::vector<int> deck(52);
    std::iota(deck.begin(), deck.end(), 0);
    // std::cout << "Deck is: ";
    // for (auto i = deck.begin(); i != deck.end(); ++i)
    //     std::cout << *i << ' ';
    // std::cout << std::endl;

    std::vector<int> deal(8);

    auto mt19937 = std::mt19937{std::random_device{}()};
    for (auto hand = 0; hand < 5000000; ++hand) {
        std::sample(deck.begin(), deck.end(), deal.begin(), 8, mt19937);

        // std::cout << "Deal is: ";
        // for (auto i = deal.begin(); i != deal.end(); ++i)
        //     std::cout << *i << ' ';
        // std::cout << std::endl;
    }

    return 0;
}